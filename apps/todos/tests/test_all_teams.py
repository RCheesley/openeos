"""The To-Dos list can show every team the user may see, as the Rocks list can."""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.accounts.scoping import SESSION_ORG_KEY, SESSION_TEAM_KEY
from apps.todos.models import ToDo
from apps.todos.views import SCOPE_SESSION_KEY

LIST_URL = '/todos/'


class AllTeamsScopeTestBase(TestCase):
    """One organisation with four teams, and a second organisation.

    ``member`` is on Alpha and Beta; ``admin`` is an organisation admin on Alpha
    only; ``solo`` is on Delta alone, which has no To-Dos; ``teamless_admin``
    is an organisation admin on no team; ``dual`` is on Alpha and Beta and
    also on Omega in the second organisation. Alpha is the active team for
    everyone on it because it sorts first by name.

    ``member`` owns an open To-Do on Alpha, an overdue and a complete one on
    Beta. ``admin`` owns an open To-Do on each of Alpha, Beta and Gamma.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name='Scope Org')
        cls.alpha = Team.objects.create(organization=cls.org, name='Alpha')
        cls.beta = Team.objects.create(organization=cls.org, name='Beta')
        cls.gamma = Team.objects.create(organization=cls.org, name='Gamma')
        cls.delta = Team.objects.create(organization=cls.org, name='Delta')

        cls.member = cls.make_user('scopemember', cls.alpha, cls.beta)
        cls.admin = cls.make_user('scopeadmin', cls.alpha, role=Membership.ROLE_ADMIN)
        cls.solo = cls.make_user('scopesolo', cls.delta)
        cls.teamless_admin = cls.make_user('scopeteamless', role=Membership.ROLE_ADMIN)

        today = date.today()
        cls.mine_alpha = cls.make_todo(cls.alpha, cls.member, 'Mine on Alpha', today + timedelta(days=5))
        cls.mine_beta_overdue = cls.make_todo(
            cls.beta, cls.member, 'Mine on Beta overdue', today - timedelta(days=2)
        )
        cls.mine_beta_done = cls.make_todo(cls.beta, cls.member, 'Mine on Beta done', today)
        cls.mine_beta_done.mark_complete()
        cls.admin_alpha = cls.make_todo(cls.alpha, cls.admin, 'Admin on Alpha', today + timedelta(days=1))
        cls.admin_beta = cls.make_todo(cls.beta, cls.admin, 'Admin on Beta', today + timedelta(days=3))
        cls.admin_gamma = cls.make_todo(cls.gamma, cls.admin, 'Admin on Gamma', today + timedelta(days=4))

        # A second organisation that ``dual`` also belongs to, with their own To-Do there.
        cls.other_org = Organization.objects.create(name='Other Org')
        cls.omega = Team.objects.create(organization=cls.other_org, name='Omega')
        cls.dual = cls.make_user('scopedual', cls.alpha, cls.beta)
        Membership.objects.create(user=cls.dual, organization=cls.other_org)
        cls.dual.profile.teams.add(cls.omega)
        cls.dual_beta = cls.make_todo(cls.beta, cls.dual, 'Dual on Beta', today + timedelta(days=2))
        cls.dual_omega = cls.make_todo(cls.omega, cls.dual, 'Dual on Omega', today + timedelta(days=2))

    @classmethod
    def make_user(cls, username, *teams, role=Membership.ROLE_MEMBER):
        user = User.objects.create_user(username=username, password='pw')
        Membership.objects.create(user=user, organization=cls.org, role=role)
        user.profile.teams.add(*teams)
        return user

    @classmethod
    def make_todo(cls, team, owner, title, due):
        return ToDo.objects.create(team=team, owner=owner, title=title, due_date=due)

    def login(self, user, **session_values):
        """Sign ``user`` in, pinning the active organisation or team if given."""
        self.client.force_login(user)
        if session_values:
            session = self.client.session
            session.update(session_values)
            session.save()

    @staticmethod
    def grouped(resp):
        """``[(team name, [titles in page order])]`` as the page groups them."""
        return [(team.name, [t.title for t in todos]) for team, todos in resp.context['teams_todos']]

    @staticmethod
    def titles(resp):
        return [t.title for t in resp.context['todos']]


class SingleTeamScopeTest(AllTeamsScopeTestBase):
    """The Mine / Team tabs and the status filters behave as they did."""

    def test_default_is_my_open_todos_on_the_active_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(resp.context['view_filter'], 'mine')
        self.assertEqual(resp.context['status_filter'], 'open')
        self.assertEqual(self.titles(resp), ['Mine on Alpha'])
        self.assertEqual(self.grouped(resp), [('Alpha', ['Mine on Alpha'])])
        # A single team gets no heading and its rows are as they were.
        self.assertNotContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')
        self.assertNotContains(resp, '<i class="bi bi-people me-1" aria-hidden="true"></i>Alpha')

    def test_team_tab_lists_everyones_open_todos_by_due_date(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'view': 'team'})
        self.assertEqual(self.titles(resp), ['Admin on Alpha', 'Mine on Alpha'])

    def test_overdue_and_complete_filters(self):
        self.login(self.member, active_team_id=self.beta.pk)
        resp = self.client.get(LIST_URL, {'view': 'mine', 'status': 'overdue'})
        self.assertEqual(self.titles(resp), ['Mine on Beta overdue'])
        resp = self.client.get(LIST_URL, {'view': 'mine', 'status': 'complete'})
        self.assertEqual(self.titles(resp), ['Mine on Beta done'])
        resp = self.client.get(LIST_URL, {'view': 'team'})
        self.assertEqual(
            self.titles(resp), ['Mine on Beta overdue', 'Dual on Beta', 'Admin on Beta']
        )

    def test_unknown_scope_value_is_ignored(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'bogus'})
        self.assertEqual(resp.context['scope'], 'team')
        self.assertNotIn(SCOPE_SESSION_KEY, self.client.session)

    def test_toggle_is_offered_to_a_user_on_several_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, 'aria-label="Which teams to show"')
        self.assertContains(resp, 'aria-current="true"', count=1)
        self.assertRegex(
            resp.content.decode(),
            r'href="\?view=mine&amp;status=open&amp;scope=team"\s+class="btn btn-dark"'
            r'\s+aria-current="true">\s+This team',
        )
        self.assertContains(resp, 'href="?view=mine&amp;status=open&amp;scope=all"')

    def test_toggle_is_absent_for_a_user_on_one_team(self):
        self.client.force_login(self.solo)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'This team')
        self.assertNotContains(resp, 'Which teams to show')
        self.assertContains(resp, 'No open Actions')


class AllScopeTest(AllTeamsScopeTestBase):
    def test_mine_in_all_teams_is_everything_i_own_on_my_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Mine on Alpha']),
            ('Beta', ['Mine on Beta overdue']),
        ])

    def test_team_tab_in_all_teams_lists_everyone_and_keeps_due_date_order(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'view': 'team'})
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Admin on Alpha', 'Mine on Alpha']),
            ('Beta', ['Mine on Beta overdue', 'Dual on Beta', 'Admin on Beta']),
        ])
        self.assertNotContains(resp, 'Admin on Gamma')

    def test_status_filters_apply_across_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'status': 'overdue'})
        self.assertEqual(self.grouped(resp), [('Beta', ['Mine on Beta overdue'])])
        resp = self.client.get(LIST_URL, {'status': 'complete'})
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.grouped(resp), [('Beta', ['Mine on Beta done'])])

    def test_each_team_is_named_in_a_heading_with_a_count_and_on_its_rows(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'view': 'team'})
        html = resp.content.decode()
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Beta</h2>')
        self.assertRegex(html, r'>\s+2\s+Actions\s+</span>')
        self.assertRegex(html, r'>\s+3\s+Actions\s+</span>')
        self.assertEqual(html.count('<i class="bi bi-people me-1" aria-hidden="true"></i>Alpha'), 2)
        self.assertEqual(html.count('<i class="bi bi-people me-1" aria-hidden="true"></i>Beta'), 3)

    def test_heading_count_uses_the_singular_term(self):
        self.org.terminology = {'todo': 'Task', 'todos': 'Tasks'}
        self.org.save()
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertRegex(resp.content.decode(), r'>\s+1\s+Task\s+</span>')
        self.assertNotContains(resp, 'Action')

    def test_all_teams_is_marked_as_the_current_choice(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'view': 'team'})
        self.assertContains(resp, 'aria-current="true"', count=1)
        self.assertRegex(
            resp.content.decode(),
            r'href="\?view=team&amp;status=open&amp;scope=all"\s+class="btn btn-dark"'
            r'\s+aria-current="true">\s+All teams',
        )
        self.assertContains(resp, 'Showing all your teams (2)')
        self.assertContains(
            resp, '<a href="?view=team&amp;status=open&amp;scope=team">Back to Alpha</a>'
        )

    def test_org_admin_sees_every_team_in_the_organisation(self):
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Admin on Alpha']),
            ('Beta', ['Admin on Beta']),
            ('Gamma', ['Admin on Gamma']),
        ])

    def test_org_admin_on_no_team_gets_all_teams(self):
        self.client.force_login(self.teamless_admin)
        resp = self.client.get(LIST_URL, {'view': 'team'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha', 'Beta', 'Gamma'])
        # There is no single team to switch back to.
        self.assertNotContains(resp, 'This team')
        self.assertNotContains(resp, 'Back to')
        self.assertNotIn(SCOPE_SESSION_KEY, self.client.session)

    def test_scope_persists_across_the_tab_and_status_links(self):
        """Those links carry no scope, so the session keeps the choice."""
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.client.session[SCOPE_SESSION_KEY], 'all')
        resp = self.client.get(LIST_URL, {'view': 'team', 'status': 'overdue'})
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.grouped(resp), [('Beta', ['Mine on Beta overdue'])])

    def test_scope_is_kept_apart_from_the_other_lists(self):
        self.assertEqual(SCOPE_SESSION_KEY, 'todos_scope')
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        for key in ('rocks_scope', 'scorecards_scope', 'issues_scope', 'meetings_scope'):
            self.assertNotIn(key, self.client.session)
        resp = self.client.get('/issues/')
        self.assertEqual(resp.context['scope'], 'team')

    def test_scope_team_returns_to_the_active_team(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        resp = self.client.get(LIST_URL, {'scope': 'team'})
        self.assertEqual(self.titles(resp), ['Mine on Alpha'])
        resp = self.client.get(LIST_URL)
        self.assertEqual(self.titles(resp), ['Mine on Alpha'])

    def test_complete_toggle_returns_to_the_same_view(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertContains(resp, 'name="next" value="/todos/?scope=all"')
        self.client.post(f'/todos/{self.mine_alpha.pk}/complete/', {'next': '/todos/?scope=all'})
        resp = self.client.get(LIST_URL)
        self.assertEqual(self.grouped(resp), [('Beta', ['Mine on Beta overdue'])])


class OrganisationBoundaryTest(AllTeamsScopeTestBase):
    def test_all_scope_never_lists_another_organisations_todos(self):
        """``dual`` belongs to both organisations; only the active one is listed."""
        self.login(self.dual, active_org_id=self.org.pk)
        for view in ('mine', 'team'):
            with self.subTest(view=view):
                resp = self.client.get(LIST_URL, {'scope': 'all', 'view': view})
                self.assertNotIn('Dual on Omega', self.titles(resp))
                self.assertIn('Dual on Beta', self.titles(resp))
                self.assertNotContains(resp, 'Omega')

    def test_the_other_organisation_lists_only_its_own(self):
        self.login(self.dual, active_org_id=self.other_org.pk)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'view': 'team'})
        self.assertEqual(self.titles(resp), ['Dual on Omega'])

    def test_hint_does_not_count_another_organisations_todos(self):
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']], [('Beta', 1)]
        )


class ScopeHintTest(AllTeamsScopeTestBase):
    def test_hint_counts_my_todos_on_other_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, 'Showing Alpha')
        self.assertContains(resp, '1 more on other teams')
        self.assertEqual(resp.context['other_todos_total'], 1)
        self.assertContains(
            resp, 'href="?view=mine&amp;status=open&amp;scope=all" title="Beta: 1"'
        )

    def test_hint_follows_the_tab_and_the_status_filter(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'view': 'team'})
        self.assertEqual(resp.context['other_todos_total'], 3)
        resp = self.client.get(LIST_URL, {'view': 'mine', 'status': 'complete'})
        self.assertEqual(resp.context['other_todos_total'], 1)
        self.assertContains(resp, 'No completed Actions')
        self.assertContains(resp, '1 more on other teams')

    def test_hint_counts_only_teams_the_user_may_see(self):
        """Gamma's To-Do counts for the admin but not for the member."""
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {'view': 'team'})
        self.assertContains(resp, '4 more on other teams')
        self.assertContains(resp, 'title="Beta: 3, Gamma: 1"')

    def test_no_hint_when_other_teams_have_nothing(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'status': 'overdue'})
        self.assertEqual(self.titles(resp), [])
        self.login(self.member, active_team_id=self.beta.pk)
        resp = self.client.get(LIST_URL, {'status': 'overdue'})
        self.assertEqual(resp.context['other_todos_total'], 0)
        self.assertNotContains(resp, 'more on other teams')


class OverdueBadgeScopeTest(TestCase):
    """The red badge beside the heading counts what the Overdue filter would list."""

    def setUp(self):
        self.org = Organization.objects.create(name='Badge Org')
        self.alpha = Team.objects.create(organization=self.org, name='Alpha')
        self.beta = Team.objects.create(organization=self.org, name='Beta')
        self.elsewhere = Organization.objects.create(name='Elsewhere Org')
        self.far = Team.objects.create(organization=self.elsewhere, name='Far')
        self.user = User.objects.create_user(username='badge', password='pw')
        self.mate = User.objects.create_user(username='badgemate', password='pw')
        for org in (self.org, self.elsewhere):
            Membership.objects.create(user=self.user, organization=org)
        Membership.objects.create(user=self.mate, organization=self.org)
        self.user.profile.teams.add(self.alpha, self.beta, self.far)
        self.mate.profile.teams.add(self.alpha)
        late = date.today() - timedelta(days=3)
        ToDo.objects.create(title='Mine on Alpha', owner=self.user, team=self.alpha, due_date=late)
        ToDo.objects.create(title='Mate on Alpha', owner=self.mate, team=self.alpha, due_date=late)
        ToDo.objects.create(title='Mine on Beta', owner=self.user, team=self.beta, due_date=late)
        ToDo.objects.create(title='Mine elsewhere', owner=self.user, team=self.far, due_date=late)
        self.client.force_login(self.user)
        session = self.client.session
        session[SESSION_ORG_KEY] = self.org.pk
        session[SESSION_TEAM_KEY] = self.alpha.pk
        session.save()

    def count(self, query):
        return self.client.get(f'/todos/?{query}').context['overdue_count']

    def test_single_team_mine_counts_only_my_overdue_on_that_team(self):
        self.assertEqual(self.count('scope=team&view=mine'), 1)

    def test_single_team_tab_counts_everyone_on_that_team(self):
        self.assertEqual(self.count('scope=team&view=team'), 2)

    def test_all_teams_never_reaches_another_organisation(self):
        self.assertEqual(self.count('scope=all&view=mine'), 2)
        self.assertEqual(self.count('scope=all&view=team'), 3)

    def test_badge_matches_the_overdue_filter(self):
        for query in ('scope=team&view=mine', 'scope=team&view=team', 'scope=all&view=mine', 'scope=all&view=team'):
            with self.subTest(query=query):
                resp = self.client.get(f'/todos/?{query}&status=overdue')
                self.assertEqual(resp.context['overdue_count'], len(resp.context['todos']))
