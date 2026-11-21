"""The meetings list can show every team the user may see, as the Rocks list can."""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.meetings.models import Meeting
from apps.meetings.views import SCOPE_SESSION_KEY

LIST_URL = '/meetings/'


class AllTeamsScopeTestBase(TestCase):
    """One organisation with four teams, and a second organisation.

    ``member`` is on Alpha and Beta; ``admin`` is an organisation admin on Alpha
    only; ``solo`` is on Delta alone, which has no meetings; ``teamless_admin``
    is an organisation admin on no team; ``loner`` is a member of the
    organisation but on no team; ``dual`` is on Alpha and Beta and also on
    Omega in the second organisation. Alpha is the active team for everyone
    on it because it sorts first by name.
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

        cls.alpha_old = cls.make_meeting(cls.alpha, date(2026, 11, 4), started=True)
        cls.alpha_next = cls.make_meeting(cls.alpha, date(2026, 11, 25))
        cls.beta_next = cls.make_meeting(cls.beta, date(2026, 11, 26))
        cls.gamma_next = cls.make_meeting(cls.gamma, date(2026, 11, 27))

        # A second organisation that ``dual`` also belongs to, with its own meeting.
        cls.other_org = Organization.objects.create(name='Other Org')
        cls.omega = Team.objects.create(organization=cls.other_org, name='Omega')
        cls.dual = cls.make_user('scopedual', cls.alpha, cls.beta)
        Membership.objects.create(user=cls.dual, organization=cls.other_org)
        cls.dual.profile.teams.add(cls.omega)
        cls.omega_next = cls.make_meeting(cls.omega, date(2026, 11, 28))

    @classmethod
    def make_user(cls, username, *teams, role=Membership.ROLE_MEMBER):
        user = User.objects.create_user(username=username, password='pw')
        Membership.objects.create(user=user, organization=cls.org, role=role)
        user.profile.teams.add(*teams)
        return user

    @classmethod
    def make_meeting(cls, team, day, started=False):
        meeting = Meeting.objects.create(team=team, scheduled_date=day, created_by=cls.admin)
        if started:
            meeting.start()
        return meeting

    def login(self, user, **session_values):
        """Sign ``user`` in, pinning the active organisation or team if given."""
        self.client.force_login(user)
        if session_values:
            session = self.client.session
            session.update(session_values)
            session.save()

    @staticmethod
    def team_names(resp):
        return [team.name for team, _ in resp.context['teams_meetings']]

    @staticmethod
    def meeting_pks(resp):
        return [m.pk for m in resp.context['meetings']]


class DefaultScopeTest(AllTeamsScopeTestBase):
    def test_default_shows_only_the_active_team(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(self.team_names(resp), ['Alpha'])
        # Newest first, as before.
        self.assertEqual(self.meeting_pks(resp), [self.alpha_next.pk, self.alpha_old.pk])
        self.assertNotContains(resp, f'/meetings/{self.beta_next.pk}/')
        # A single team gets no heading; each row already names its team.
        self.assertNotContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')

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
        self.assertNotContains(resp, 'All teams')

    def test_user_with_no_teams_is_still_sent_home(self):
        self.client.force_login(self.loner)
        for params in ({}, {'scope': 'all'}):
            with self.subTest(params=params):
                resp = self.client.get(LIST_URL, params)
                self.assertRedirects(resp, '/', fetch_redirect_response=False)


class AllScopeTest(AllTeamsScopeTestBase):
    def test_all_scope_groups_the_users_teams_and_skips_others(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta'])
        self.assertEqual(
            self.meeting_pks(resp), [self.alpha_next.pk, self.alpha_old.pk, self.beta_next.pk]
        )
        self.assertEqual([t.name for t in resp.context['scoped_teams']], ['Alpha', 'Beta'])
        self.assertNotContains(resp, f'/meetings/{self.gamma_next.pk}/')
        self.assertNotContains(resp, 'Gamma')

    def test_each_team_is_named_in_a_heading_and_on_its_rows(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Alpha</h2>')
        self.assertContains(resp, '<h2 class="h5 mb-0 me-2">Beta</h2>')
        self.assertContains(resp, '<td>Alpha</td>', count=2)
        self.assertContains(resp, '<td>Beta</td>', count=1)
        self.assertRegex(resp.content.decode(), r'>\s+2\s+Weekly Meetings\s+</span>')
        self.assertRegex(resp.content.decode(), r'>\s+1\s+Weekly Meeting\s+</span>')

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
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta', 'Gamma'])
        self.assertContains(resp, f'/meetings/{self.gamma_next.pk}/')

    def test_org_admin_on_no_team_gets_all_teams(self):
        self.client.force_login(self.teamless_admin)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta', 'Gamma'])
        # There is no single team to switch back to.
        self.assertNotContains(resp, 'This team')
        self.assertNotIn(SCOPE_SESSION_KEY, self.client.session)

    def test_scope_persists_in_the_session(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.client.session[SCOPE_SESSION_KEY], 'all')
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['scope'], 'all')
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta'])

    def test_scope_is_kept_apart_from_the_other_lists(self):
        self.assertEqual(SCOPE_SESSION_KEY, 'meetings_scope')
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        self.assertNotIn('rocks_scope', self.client.session)
        self.assertNotIn('scorecards_scope', self.client.session)

    def test_scope_team_returns_to_the_active_team(self):
        self.client.force_login(self.member)
        self.client.get(LIST_URL, {'scope': 'all'})
        resp = self.client.get(LIST_URL, {'scope': 'team'})
        self.assertEqual(resp.context['scope'], 'team')
        self.assertEqual(self.team_names(resp), ['Alpha'])
        resp = self.client.get(LIST_URL)
        self.assertEqual(self.team_names(resp), ['Alpha'])

    def test_empty_state_names_all_teams(self):
        self.client.force_login(self.solo)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.context['teams_meetings'], [])
        self.assertContains(resp, 'No weekly meetings on any of your teams yet')

    def test_single_team_empty_state_is_unchanged(self):
        self.client.force_login(self.solo)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, 'No weekly meetings yet')
        self.assertNotContains(resp, 'on any of your teams')


class OrganisationBoundaryTest(AllTeamsScopeTestBase):
    def test_all_scope_never_lists_another_organisations_meetings(self):
        """``dual`` belongs to both organisations; only the active one is listed."""
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.context['org'], self.org)
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta'])
        self.assertNotIn(self.omega_next.pk, self.meeting_pks(resp))
        self.assertNotContains(resp, f'/meetings/{self.omega_next.pk}/')
        self.assertNotContains(resp, '<td>Omega</td>')

    def test_the_other_organisation_lists_only_its_own(self):
        self.login(self.dual, active_org_id=self.other_org.pk)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(resp.context['org'], self.other_org)
        self.assertEqual(self.meeting_pks(resp), [self.omega_next.pk])

    def test_hint_does_not_count_another_organisations_meetings(self):
        self.login(self.dual, active_org_id=self.org.pk)
        resp = self.client.get(LIST_URL)
        self.assertEqual(
            [(t.name, n) for t, n in resp.context['other_team_counts']], [('Beta', 1)]
        )

    def test_superuser_is_kept_to_the_active_organisation(self):
        root = User.objects.create_superuser(username='scoperoot', password='pw')
        Membership.objects.create(user=root, organization=self.org)
        self.client.force_login(root)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertEqual(self.team_names(resp), ['Alpha', 'Beta', 'Gamma'])
        self.assertNotIn(self.omega_next.pk, self.meeting_pks(resp))


class ScopeHintTest(AllTeamsScopeTestBase):
    def test_team_scope_hints_at_meetings_on_other_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, 'Showing Alpha')
        self.assertContains(resp, '1 more on other teams')
        self.assertEqual(resp.context['other_meetings_total'], 1)
        self.assertContains(resp, 'href="?scope=all" title="Beta: 1"')

    def test_hint_counts_only_teams_the_user_may_see(self):
        """Gamma's meeting counts for the admin but not for the member."""
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL)
        self.assertContains(resp, '2 more on other teams')
        self.assertContains(resp, 'title="Beta: 1, Gamma: 1"')

    def test_no_hint_when_other_teams_have_nothing(self):
        Meeting.objects.filter(pk=self.beta_next.pk).delete()
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['other_meetings_total'], 0)
        self.assertNotContains(resp, 'more on other teams')

    def test_hint_shows_above_the_empty_state(self):
        """A team with nothing scheduled still points at the other teams' meetings."""
        self.member.profile.teams.add(self.delta)
        self.login(self.member, active_team_id=self.delta.pk)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['active_team'], self.delta)
        self.assertContains(resp, 'No weekly meetings yet')
        self.assertContains(resp, '3 more on other teams')
        self.assertContains(resp, 'title="Alpha: 2, Beta: 1"')


class ControlsInAllScopeTest(AllTeamsScopeTestBase):
    def edit_url(self, meeting):
        return f'/meetings/{meeting.pk}/edit/'

    def delete_url(self, meeting):
        return f'/meetings/{meeting.pk}/delete/'

    def test_member_gets_edit_and_delete_on_scheduled_meetings_of_their_teams(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        for meeting in (self.alpha_next, self.beta_next):
            self.assertContains(resp, self.edit_url(meeting))
            self.assertContains(resp, self.delete_url(meeting))
        self.assertContains(resp, 'aria-label="Edit Beta Weekly Meeting on Nov. 26, 2026"')
        self.assertContains(resp, 'aria-label="Delete Beta Weekly Meeting on Nov. 26, 2026"')

    def test_started_meeting_has_no_edit_or_delete(self):
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertNotContains(resp, self.edit_url(self.alpha_old))
        self.assertNotContains(resp, self.delete_url(self.alpha_old))
        self.assertContains(resp, f'href="/meetings/{self.alpha_old.pk}/"')

    def test_admin_gets_edit_and_delete_on_a_team_they_are_not_on(self):
        self.client.force_login(self.admin)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        self.assertContains(resp, self.edit_url(self.gamma_next))
        self.assertContains(resp, self.delete_url(self.gamma_next))

    def test_each_row_follows_the_per_meeting_rule(self):
        """``can_change`` on every listed row matches ``Meeting.can_be_changed_by``."""
        for user in (self.member, self.admin, self.teamless_admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                resp = self.client.get(LIST_URL, {'scope': 'all'})
                self.assertTrue(resp.context['meetings'])
                for meeting in resp.context['meetings']:
                    self.assertEqual(meeting.can_change, meeting.can_be_changed_by(user))
                    shown = self.edit_url(meeting) in resp.content.decode()
                    self.assertEqual(shown, meeting.can_change)

    def test_start_link_is_labelled_by_status(self):
        self.client.force_login(self.member)
        resp = self.client.get(LIST_URL, {'scope': 'all'})
        html = resp.content.decode()
        self.assertEqual(html.count('</i>Start'), 2)
        self.assertEqual(html.count('</i>Run'), 1)
