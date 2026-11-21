"""The API shows a caller what the web shows them, and nothing more."""
from datetime import date

from django.contrib.auth.models import User

from apps.accounts.models import Membership, Team
from apps.accounts.team_scope import SCOPE_ALL
from apps.issues.models import Issue
from apps.rocks.models import Rock, RockCheckin, RockMilestone
from apps.todos.models import ToDo

from .helpers import ApiTestCase, issue_token


class TeamVisibilityTest(ApiTestCase):
    """One organisation, two teams. Mo is a member of Alpha only; the admin sees both."""

    def setUp(self):
        super().setUp()
        self.admin = self.user
        self.alpha = self.mine['team']
        self.beta = Team.objects.create(organization=self.org, name='Beta')
        self.mo = User.objects.create_user('mo', password='pw', first_name='Mo', last_name='Member')
        Membership.objects.create(user=self.mo, organization=self.org, role=Membership.ROLE_MEMBER)
        self.mo.profile.teams.add(self.alpha)
        self.bea = User.objects.create_user('bea', password='pw')
        Membership.objects.create(user=self.bea, organization=self.org, role=Membership.ROLE_MEMBER)
        self.bea.profile.teams.add(self.beta)

        quarter = {'quarter': 1, 'year': 2026, 'due_date': date(2026, 3, 31)}
        self.alpha_rock = self.mine['rock']
        self.beta_rock = Rock.objects.create(title='Beta priority', owner=self.bea, team=self.beta, **quarter)
        self.beta_todo = ToDo.objects.create(title='Beta action', owner=self.bea, team=self.beta)
        self.mo_todo_in_beta = ToDo.objects.create(title='Mo helps Beta', owner=self.mo, team=self.beta)
        self.beta_issue = Issue.objects.create(title='Beta blocker', originating_team=self.beta)
        self.handed_over = Issue.objects.create(
            title='Handed to Alpha', originating_team=self.beta, delegated_to_team=self.alpha,
        )
        self.mo_token = issue_token(self.mo, self.org)

    def ids(self, path, token=None):
        return {row['id'] for row in self.results(path, token)}

    def test_member_lists_only_their_teams_priorities(self):
        ids = self.ids('priorities', self.mo_token)
        self.assertIn(self.alpha_rock.pk, ids)
        self.assertNotIn(self.beta_rock.pk, ids)

    def test_admin_lists_every_teams_priorities(self):
        ids = self.ids('priorities')
        self.assertLessEqual({self.alpha_rock.pk, self.beta_rock.pk}, ids)

    def test_priority_list_matches_the_web_list_for_the_same_user(self):
        """The same rows the web's all-teams list shows for the quarter."""
        for user, token in ((self.mo, self.mo_token), (self.admin, self.token)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get('/rocks/', {'quarter': 1, 'year': 2026, 'scope': SCOPE_ALL})
                web_ids = {rock.pk for rock in page.context['rocks']}
                self.client.logout()
                self.assertEqual(self.ids('priorities?quarter=1&year=2026', token), web_ids)

    def test_member_cannot_widen_a_list_with_the_team_filter(self):
        self.assertEqual(self.results(f'priorities?team={self.beta.pk}', self.mo_token), [])
        self.assertEqual(self.ids(f'priorities?team={self.beta.pk}'), {self.beta_rock.pk})

    def test_actions_cover_the_members_teams_and_anything_they_own(self):
        ids = self.ids('actions', self.mo_token)
        self.assertIn(self.mine['todo'].pk, ids)       # Alpha's
        self.assertIn(self.mo_todo_in_beta.pk, ids)    # Mo's own, filed under Beta
        self.assertNotIn(self.beta_todo.pk, ids)       # Beta's, someone else's
        self.assertEqual(self.ids('actions?mine=true', self.mo_token), {self.mo_todo_in_beta.pk})

    def test_blockers_cover_those_raised_by_or_handed_to_the_members_teams(self):
        ids = self.ids('blockers', self.mo_token)
        self.assertIn(self.mine['issue'].pk, ids)
        self.assertIn(self.handed_over.pk, ids)
        self.assertNotIn(self.beta_issue.pk, ids)

    def test_teams_list_is_the_whole_organisation_as_on_the_web(self):
        self.assertEqual(self.ids('teams', self.mo_token), {self.alpha.pk, self.beta.pk})

    def test_by_id_follows_the_web_detail_page(self):
        """The web opens any record of the organisation by its address; so does the API."""
        self.client.force_login(self.mo)
        web = self.client.get(f'/rocks/{self.beta_rock.pk}/').status_code
        self.client.logout()
        api = self.api_get(f'priorities/{self.beta_rock.pk}', self.mo_token).status_code
        self.assertEqual((web, api), (200, 200))

    def test_me_reports_role_and_teams(self):
        me = self.api_get('me', self.mo_token).json()
        self.assertEqual(me['role'], 'member')
        self.assertFalse(me['is_organisation_admin'])
        self.assertEqual(me['team_ids'], [self.alpha.pk])
        self.assertEqual(me['name'], 'Mo Member')
        admin = self.api_get('me').json()
        self.assertEqual(admin['role'], 'admin')
        self.assertTrue(admin['is_organisation_admin'])


class RepresentationTest(ApiTestCase):
    def test_priority_uses_generic_names(self):
        body = self.api_get(f'priorities/{self.mine["rock"].pk}').json()
        self.assertEqual(body['title'], 'Mine Rock')
        self.assertEqual(body['status'], 'on_track')
        self.assertEqual(body['team_id'], self.mine['team'].pk)
        self.assertEqual(body['owner'], {'id': self.user.pk, 'name': self.user.username})
        self.assertEqual(body['due_date'], '2026-03-31')
        self.assertTrue(body['updated_at'].endswith('Z'))
        self.assertFalse(any('rock' in key for key in body))

    def test_steps_and_check_ins_hang_off_their_priority(self):
        rock = self.mine['rock']
        RockMilestone.objects.create(rock=rock, title='Second', order=5)
        RockCheckin.objects.create(rock=rock, confidence='off_track', note='Slipping', created_by=self.user)
        steps = self.results(f'priorities/{rock.pk}/steps')
        self.assertEqual([s['title'] for s in steps], ['Mine Milestone', 'Second'])
        self.assertEqual({s['priority_id'] for s in steps}, {rock.pk})
        check_ins = self.results(f'priorities/{rock.pk}/check-ins')
        self.assertEqual(check_ins[0]['confidence'], 'off_track')
        self.assertEqual(check_ins[0]['created_by']['id'], self.user.pk)

    def test_blocker_status_has_its_own_fixed_word(self):
        issue = self.mine['issue']
        issue.status = Issue.STATUS_IN_IDS
        issue.save()
        self.assertEqual(self.api_get(f'blockers/{issue.pk}').json()['status'], 'in_discussion')
        self.assertEqual(len(self.results('blockers?status=in_discussion')), 1)
        self.assertEqual(self.results('blockers?status=open'), [])
        self.assertProblem(self.api_get('blockers?status=in_ids'), 400)

    def test_blocker_and_action_links(self):
        self.mine['rock'].linked_issues.add(self.mine['issue'])
        todo = self.mine['todo']
        todo.linked_rock, todo.linked_issue = self.mine['rock'], self.mine['issue']
        todo.save()
        blocker = self.api_get(f'blockers/{self.mine["issue"].pk}').json()
        self.assertEqual(blocker['priority_ids'], [self.mine['rock'].pk])
        action = self.api_get(f'actions/{todo.pk}').json()
        self.assertEqual((action['priority_id'], action['blocker_id']), (self.mine['rock'].pk, self.mine['issue'].pk))

    def test_organisation_returns_its_own_words_under_fixed_keys(self):
        self.org.terminology = {'rock': 'Rock', 'rocks': 'Rocks', 'todo': 'Task'}
        self.org.tagline = 'Lights on'
        self.org.save()
        body = self.api_get('organisation').json()
        self.assertEqual(body['vocabulary']['priority'], {'singular': 'Rock', 'plural': 'Rocks'})
        self.assertEqual(body['vocabulary']['action'], {'singular': 'Task', 'plural': 'Actions'})
        self.assertEqual(body['vocabulary']['blocker'], {'singular': 'Blocker', 'plural': 'Blockers'})
        self.assertEqual(body['branding']['tagline'], 'Lights on')
        self.assertEqual(body['branding']['display_name'], 'Mine Org')

    def test_every_term_has_a_fixed_api_key(self):
        from apps.accounts.terminology import TERM_KEYS
        from apps.api.terminology import API_TERM_KEYS
        self.assertEqual(set(API_TERM_KEYS), set(TERM_KEYS))
        self.assertEqual(len(set(API_TERM_KEYS.values())), len(API_TERM_KEYS))
