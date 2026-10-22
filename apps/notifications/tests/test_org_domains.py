from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.models import Membership, Organization, OrganizationDomain, Team
from apps.meetings.models import Meeting
from apps.notifications.emails import (
    send_meeting_reminder,
    send_overdue_todo_digest,
    send_rock_off_track_alert,
    send_user_invite_email,
)
from apps.rocks.models import Rock
from apps.todos.models import ToDo


@override_settings(SITE_URL='https://eos.example.test')
class OrgDomainEmailLinksTest(TestCase):
    """Emails for an organisation link to its own domain, or SITE_URL when it has none."""

    def setUp(self):
        self.user = User.objects.create_user(username='mailee', email='mailee@example.com', password='pw')
        self.mercury = Organization.objects.create(name='Mercury Org')
        OrganizationDomain.objects.create(organization=self.mercury, hostname='mercury.example.test')
        self.mercury_team = Team.objects.create(organization=self.mercury, name='Mercury Team')
        self.plain = Organization.objects.create(name='Plain Org')
        self.plain_team = Team.objects.create(organization=self.plain, name='Plain Team')
        for org in (self.mercury, self.plain):
            Membership.objects.create(user=self.user, organization=org)

    def _todo(self, team, title):
        return ToDo.objects.create(
            title=title, owner=self.user, team=team, due_date=date.today() - timedelta(days=1),
        )

    def test_overdue_digest_links_to_the_org_domain(self):
        todo = self._todo(self.mercury_team, 'Mercury thing')
        send_overdue_todo_digest(self.user, [todo], organization=self.mercury)
        self.assertIn('https://mercury.example.test/todos/', mail.outbox[0].body)
        self.assertNotIn('eos.example.test', mail.outbox[0].body)

    def test_overdue_digest_falls_back_to_site_url(self):
        todo = self._todo(self.plain_team, 'Plain thing')
        send_overdue_todo_digest(self.user, [todo], organization=self.plain)
        self.assertIn('https://eos.example.test/todos/', mail.outbox[0].body)
        mail.outbox.clear()
        send_overdue_todo_digest(self.user, [todo])
        self.assertIn('https://eos.example.test/todos/', mail.outbox[0].body)

    def test_primary_domain_wins_over_an_alias(self):
        OrganizationDomain.objects.create(
            organization=self.mercury, hostname='hg.example.test', is_primary=True
        )
        todo = self._todo(self.mercury_team, 'Mercury thing')
        send_overdue_todo_digest(self.user, [todo], organization=self.mercury)
        self.assertIn('https://hg.example.test/todos/', mail.outbox[0].body)

    def test_meeting_reminder_links_to_the_teams_org_domain(self):
        meeting = Meeting.objects.create(team=self.mercury_team, scheduled_date=date.today())
        send_meeting_reminder(self.user, meeting)
        self.assertIn(f'https://mercury.example.test{meeting.get_absolute_url()}', mail.outbox[0].body)

    def test_rock_alert_links_to_the_teams_org_domain(self):
        rock = Rock.objects.create(
            title='Mercury Rock', owner=self.user, team=self.mercury_team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), status=Rock.STATUS_OFF_TRACK,
        )
        send_rock_off_track_alert(rock)
        self.assertIn(f'https://mercury.example.test{rock.get_absolute_url()}', mail.outbox[0].body)

    def test_rock_alert_falls_back_to_site_url(self):
        rock = Rock.objects.create(
            title='Plain Rock', owner=self.user, team=self.plain_team,
            quarter=1, year=2026, due_date=date(2026, 3, 31), status=Rock.STATUS_OFF_TRACK,
        )
        send_rock_off_track_alert(rock)
        self.assertIn(f'https://eos.example.test{rock.get_absolute_url()}', mail.outbox[0].body)

    def test_invite_email_keeps_the_reset_url_it_is_given(self):
        send_user_invite_email(self.user, self.mercury, 'https://mercury.example.test/accounts/reset/x/y/')
        self.assertIn('https://mercury.example.test/accounts/reset/x/y/', mail.outbox[0].body)


@override_settings(SITE_URL='https://eos.example.test')
class DigestPerOrganisationCommandTest(TestCase):
    """The daily command sends one digest per organisation to a user with overdue To-Dos in several."""

    def setUp(self):
        self.user = User.objects.create_user(username='busy', email='busy@example.com', password='pw')
        self.mercury = Organization.objects.create(name='Mercury Org')
        OrganizationDomain.objects.create(organization=self.mercury, hostname='mercury.example.test')
        self.silavapi = Organization.objects.create(name='Silavapi Org')
        OrganizationDomain.objects.create(organization=self.silavapi, hostname='silavapi.example.test')
        self.plain = Organization.objects.create(name='Plain Org')
        self.teams = {
            org: Team.objects.create(organization=org, name=f'{org.name} Team')
            for org in (self.mercury, self.silavapi, self.plain)
        }
        for org, team in self.teams.items():
            Membership.objects.create(user=self.user, organization=org)
            self.user.profile.teams.add(team)
            ToDo.objects.create(
                title=f'{org.name} late', owner=self.user, team=team,
                due_date=date.today() - timedelta(days=1),
            )

    def test_one_digest_per_org_each_linking_to_its_own_domain(self):
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 3)
        bodies = {m.body for m in mail.outbox}
        for org, base in [
            (self.mercury, 'https://mercury.example.test/todos/'),
            (self.silavapi, 'https://silavapi.example.test/todos/'),
            (self.plain, 'https://eos.example.test/todos/'),
        ]:
            with self.subTest(org=org.name):
                body = next(b for b in bodies if f'{org.name} late' in b)
                self.assertIn(base, body)
                for other in {self.mercury, self.silavapi, self.plain} - {org}:
                    self.assertNotIn(f'{other.name} late', body)

    def test_two_overdue_todos_in_one_org_share_a_digest(self):
        ToDo.objects.create(
            title='Mercury also late', owner=self.user, team=self.teams[self.mercury],
            due_date=date.today() - timedelta(days=5),
        )
        call_command('send_daily_notifications')
        self.assertEqual(len(mail.outbox), 3)
        mercury_body = next(m.body for m in mail.outbox if 'Mercury Org late' in m.body)
        self.assertIn('Mercury also late', mercury_body)
