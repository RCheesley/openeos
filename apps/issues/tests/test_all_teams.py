"""The Issues list can show every team the user may see, as the Rocks list can."""
import csv
import io

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.issues.models import Issue
from apps.issues.views import SCOPE_SESSION_KEY

LIST_URL = '/issues/'
EXPORT_URL = '/issues/export/'


class AllTeamsScopeTestBase(TestCase):
    """One organisation with four teams, and a second organisation.

    ``member`` is on Alpha and Beta; ``admin`` is an organisation admin on Alpha
    only; ``solo`` is on Delta alone, which has no Issues; ``teamless_admin``
    is an organisation admin on no team; ``loner`` is a member of the
    organisation but on no team; ``dual`` is on Alpha and Beta and also on
    Omega in the second organisation. Alpha is the active team for everyone
    on it because it sorts first by name.

    Alpha raised two open Issues, one of them delegated to Beta, and one
    resolved Issue. Beta and Gamma raised one open Issue each, and Gamma's
    is delegated to Alpha.
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
        cls.loner = cls.make_user('scopeloner')

        cls.alpha_open = cls.make_issue(cls.alpha, 'Alpha open')
        cls.alpha_to_beta = cls.make_issue(cls.alpha, 'Alpha handed to Beta', delegated_to_team=cls.beta)
        cls.alpha_resolved = cls.make_issue(cls.alpha, 'Alpha resolved', status=Issue.STATUS_RESOLVED)
        cls.beta_open = cls.make_issue(cls.beta, 'Beta open')
        cls.gamma_to_alpha = cls.make_issue(cls.gamma, 'Gamma handed to Alpha', delegated_to_team=cls.alpha)

        # A second organisation that ``dual`` also belongs to, with its own Issue.
        cls.other_org = Organization.objects.create(name='Other Org')
        cls.omega = Team.objects.create(organization=cls.other_org, name='Omega')
        cls.dual = cls.make_user('scopedual', cls.alpha, cls.beta)
        Membership.objects.create(user=cls.dual, organization=cls.other_org)
        cls.dual.profile.teams.add(cls.omega)
        cls.omega_open = cls.make_issue(cls.omega, 'Omega open')

    @classmethod
    def make_user(cls, username, *teams, role=Membership.ROLE_MEMBER):
        user = User.objects.create_user(username=username, password='pw')
        Membership.objects.create(user=user, organization=cls.org, role=role)
        user.profile.teams.add(*teams)
        return user

    @classmethod
    def make_issue(cls, team, title, **kwargs):
        return Issue.objects.create(originating_team=team, title=title, created_by=cls.admin, **kwargs)

    def login(self, user, **session_values):
        """Sign ``user`` in, pinning the active organisation or team if given."""
        self.client.force_login(user)
        if session_values:
            session = self.client.session
            session.update(session_values)
            session.save()

    @staticmethod
    def grouped(resp):
        """``[(team name, [titles])]`` as the page groups them."""
        return [
            (team.name, sorted(i.title for i in issues))
            for team, issues in resp.context['teams_issues']
        ]

    @staticmethod
    def titles(resp):
        return sorted(i.title for i in resp.context['issues'])

    @staticmethod
    def csv_titles(resp):
        rows = list(csv.reader(io.StringIO(resp.content.decode('utf-8'))))
        return [row[0] for row in rows[1:]]


class DefaultScopeTest(AllTeamsScopeTestBase):
    def test_default_shows_only_the_active_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(
            self.grouped(resp), [('Alpha', ['Alpha handed to Beta', 'Alpha open'])]
        )
        self.assertNotContains(resp, 'Beta open')
        # A single team gets no heading; each row already names its team.
        self.assertNotContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')

    def test_single_team_order_is_newest_first_as_before(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            [i.pk for i in resp.context['issues']],
            [self.alpha_to_beta.pk, self.alpha_open.pk],
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
        self.assertContains(resp, 'href="?scope=all"')
        self.assertContains(resp, 'aria-current="true"', count=1)
        self.assertRegex(
            resp.content.decode(),
            r'href="\?scope=team"\s+class="btn btn-dark"\s+aria-current="true">\s+This team',
        )

    def test_toggle_is_absent_for_a_user_on_one_team(self):
        self.client.force_login(self.solo)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([t.name for t in resp.context['visible_teams']], ['Delta'])
        self.assertNotContains(resp, 'This team')
        self.assertNotContains(resp, 'Which teams to show')

    def test_user_with_no_teams_sees_an_empty_list(self):
        self.client.force_login(self.loner)
        for params in ({}, {'scope': 'all'}):
            with self.subTest(params=params):
                resp = self.client.get(LIST_URL, params)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(self.titles(resp), [])
                self.assertEqual(resp.context['teams_issues'], [])
                self.assertNotContains(resp, 'Which teams to show')


class AllScopeTest(AllTeamsScopeTestBase):
    def test_all_scope_groups_the_users_teams_and_skips_others(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Alpha handed to Beta', 'Alpha open']),
            ('Beta', ['Beta open']),
        ])
        self.assertEqual([t.name for t in resp.context['scoped_teams']], ['Alpha', 'Beta'])
        # Gamma's Issue is delegated to Alpha but was not raised by one of the
        # member's teams, so it stays on the "delegated to us" view.
        self.assertNotContains(resp, 'Gamma handed to Alpha')

    def test_each_team_is_named_in_a_heading_with_a_count_and_on_its_rows(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        html = resp.content.decode()
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Beta</h2>')
        self.assertRegex(html, r'>\s+2\s+Blockers\s+</span>')
        self.assertRegex(html, r'>\s+1\s+Blocker\s+</span>')
        # Two rows raised by Alpha and one by Beta, each naming its team.
        self.assertEqual(html.count('<i class="bi bi-people me-1"></i>Alpha'), 2)
        self.assertEqual(html.count('<i class="bi bi-people me-1"></i>Beta'), 1)
        self.assertContains(resp, '3 Blockers')

    def test_headings_follow_the_organisations_terminology(self):
        self.org.terminology = {'issue': 'Snag', 'issues': 'Snags'}
        self.org.save()
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        html = resp.content.decode()
        self.assertRegex(html, r'>\s+2\s+Snags\s+</span>')
        self.assertRegex(html, r'>\s+1\s+Snag\s+</span>')
        self.assertNotContains(resp, 'Blocker')

    def test_all_teams_is_marked_as_the_current_choice(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertContains(resp, 'aria-current="true"', count=1)
        self.assertRegex(
            resp.content.decode(),
            r'href="\?scope=all"\s+class="btn btn-dark"\s+aria-current="true">\s+All teams',
        )
        self.assertContains(resp, 'Showing all your teams (2)')
        self.assertContains(resp, '<a href="?scope=team">Back to Alpha</a>')

    def test_org_admin_sees_every_team_in_the_organisation(self):
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Alpha handed to Beta', 'Alpha open']),
            ('Beta', ['Beta open']),
            ('Gamma', ['Gamma handed to Alpha']),
        ])

    def test_org_admin_on_no_team_gets_all_teams(self):
        self.client.force_login(self.teamless_admin)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha', 'Beta', 'Gamma'])
        # There is no single team to switch back to.
        self.assertNotContains(resp, 'This team')
        self.assertNotContains(resp, 'Back to')
        self.assertNotIn(SCOPE_SESSION_KEY, self.client.session)

    def test_scope_persists_in_the_session(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.client.session[SCOPE_SESSION_KEY], 'all')
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha', 'Beta'])

    def test_scope_is_kept_apart_from_the_other_lists(self):
        self.assertEqual(SCOPE_SESSION_KEY, 'issues_scope')
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        for key in ('rocks_scope', 'scorecards_scope', 'todos_scope', 'meetings_scope'):
            self.assertNotIn(key, self.client.session)
        resp = self.client.get('/todos/')
        self.assertEqual(resp.context['scope'], 'team')

    def test_scope_team_returns_to_the_active_team(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        resp = self.client.get(LIST_URL, {'scope': 'team'})
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha'])
        resp = self.client.get(LIST_URL)
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha'])

    def test_status_and_type_filters_still_apply(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'status': 'resolved'})
        self.assertEqual(self.grouped(resp), [('Alpha', ['Alpha resolved'])])
        resp = self.client.get(LIST_URL, {'status': 'all', 'type': 'long_term'})
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.grouped(resp), [])
        self.assertContains(resp, 'No Blockers found')

    def test_scope_links_keep_the_filters(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'status': 'resolved', 'type': 'short_term'})
        self.assertEqual(resp.context['filter_query'], 'status=resolved&type=short_term')
        self.assertContains(resp, 'href="?status=resolved&amp;type=short_term&amp;scope=all"')


class DelegatedIssueTest(AllTeamsScopeTestBase):
    def test_delegated_issue_is_listed_once_under_the_team_that_raised_it(self):
        """The member is on both the raising team and the team it went to."""
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        pks = [i.pk for i in resp.context['issues']]
        self.assertEqual(pks.count(self.alpha_to_beta.pk), 1)
        grouped = dict(self.grouped(resp))
        self.assertIn('Alpha handed to Beta', grouped['Alpha'])
        self.assertNotIn('Alpha handed to Beta', grouped['Beta'])
        self.assertContains(resp, f'href="/issues/{self.alpha_to_beta.pk}/" class="text-decoration-none', count=1)
        # The row still shows where it went.
        self.assertContains(resp, '<i class="bi bi-arrow-right me-1"></i>Beta', count=1)

    def test_delegated_view_groups_by_the_receiving_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all', 'view': 'delegated'})
        self.assertEqual(self.grouped(resp), [
            ('Alpha', ['Gamma handed to Alpha']),
            ('Beta', ['Alpha handed to Beta']),
        ])
        self.assertEqual(len(resp.context['issues']), 2)

    def test_delegated_view_in_team_scope_is_unchanged(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'view': 'delegated'})
        self.assertEqual(self.grouped(resp), [('Alpha', ['Gamma handed to Alpha'])])
        # The hint counts what the other teams have been handed.
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']], [('Beta', 1)]
        )
        self.assertContains(resp, 'href="?view=delegated&amp;scope=all" title="Beta: 1"')


class OrganisationBoundaryTest(AllTeamsScopeTestBase):
    def test_all_scope_never_lists_another_organisations_issues(self):
        """``dual`` belongs to both organisations; only the active one is listed."""
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha', 'Beta'])
        self.assertNotIn('Omega open', self.titles(resp))
        self.assertNotContains(resp, 'Omega')

    def test_the_other_organisation_lists_only_its_own(self):
        self.login(self.dual, active_org_id=self.other_org.pk)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.titles(resp), ['Omega open'])

    def test_hint_does_not_count_another_organisations_issues(self):
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']], [('Beta', 1)]
        )

    def test_export_never_includes_another_organisations_issues(self):
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(EXPORT_URL, {'scope': 'all', 'status': 'all'})
        self.assertNotIn('Omega open', self.csv_titles(resp))

    def test_superuser_is_kept_to_the_active_organisation(self):
        root = User.objects.create_superuser(username='scoperoot', password='pw')
        Membership.objects.create(user=root, organization=self.org)
        self.client.force_login(root)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual([name for name, _ in self.grouped(resp)], ['Alpha', 'Beta', 'Gamma'])
        self.assertNotIn('Omega open', self.titles(resp))


class ScopeHintTest(AllTeamsScopeTestBase):
    def test_team_scope_hints_at_issues_on_other_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, 'Showing Alpha')
        self.assertContains(resp, '1 more on other teams')
        self.assertEqual(resp.context['other_issues_total'], 1)
        self.assertContains(resp, 'href="?scope=all" title="Beta: 1"')

    def test_hint_counts_only_teams_the_user_may_see(self):
        """Gamma's Issue counts for the admin but not for the member."""
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, '2 more on other teams')
        self.assertContains(resp, 'title="Beta: 1, Gamma: 1"')

    def test_hint_follows_the_status_filter(self):
        self.make_issue(self.beta, 'Beta resolved', status=Issue.STATUS_RESOLVED)
        self.make_issue(self.beta, 'Beta dropped', status=Issue.STATUS_DROPPED)
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'status': 'resolved'})
        self.assertEqual(resp.context['other_issues_total'], 1)
        resp = self.client.get(LIST_URL, {'status': 'all'})
        self.assertEqual(resp.context['other_issues_total'], 3)

    def test_no_hint_when_other_teams_have_nothing(self):
        Issue.objects.filter(pk=self.beta_open.pk).delete()
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['other_issues_total'], 0)
        self.assertNotContains(resp, 'more on other teams')

    def test_hint_shows_above_the_empty_state(self):
        """A team with nothing raised still points at the other teams' Issues."""
        self.member.profile.teams.add(self.delta)
        self.login(self.member, active_team_id=self.delta.pk)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['active_team'], self.delta)
        self.assertContains(resp, 'No Blockers found')
        self.assertContains(resp, '3 more on other teams')
        self.assertContains(resp, 'title="Alpha: 2, Beta: 1"')


class CsvExportScopeTest(AllTeamsScopeTestBase):
    def test_export_defaults_to_the_active_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(EXPORT_URL)
        self.assertEqual(sorted(self.csv_titles(resp)), ['Alpha handed to Beta', 'Alpha open'])

    def test_export_follows_the_scope_chosen_on_the_list(self):
        """The list's Export link carries no scope; the session supplies it."""
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        resp = self.client.get(EXPORT_URL)
        # Team by team, and the delegated Issue once.
        self.assertEqual(
            self.csv_titles(resp), ['Alpha handed to Beta', 'Alpha open', 'Beta open']
        )

    def test_export_follows_the_scope_and_filters_together(self):
        self.client.force_login(self.admin)
        resp = self.client.get(EXPORT_URL, {'scope': 'all', 'status': 'all'})
        self.assertEqual(sorted(self.csv_titles(resp)), [
            'Alpha handed to Beta', 'Alpha open', 'Alpha resolved', 'Beta open',
            'Gamma handed to Alpha',
        ])

    def test_export_returns_to_one_team_with_the_list(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        self.client.get(LIST_URL, {'scope': 'team'})
        resp = self.client.get(EXPORT_URL)
        self.assertEqual(sorted(self.csv_titles(resp)), ['Alpha handed to Beta', 'Alpha open'])

    def test_export_for_an_admin_on_no_team_covers_every_team(self):
        self.client.force_login(self.teamless_admin)
        resp = self.client.get(EXPORT_URL)
        self.assertEqual(
            self.csv_titles(resp),
            ['Alpha handed to Beta', 'Alpha open', 'Beta open', 'Gamma handed to Alpha'],
        )
