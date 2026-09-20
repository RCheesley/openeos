from datetime import date, timedelta

from django.core import mail
from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Organization, Team
from apps.meetings.models import Meeting
from apps.notifications.emails import (
    send_meeting_reminder,
    send_overdue_todo_digest,
    send_rock_off_track_alert,
    send_user_invite_email,
)
from apps.notifications.models import NotificationPreference
from apps.rocks.models import Rock
from apps.todos.models import ToDo


def make_user(username, email='user@example.com'):
    return User.objects.create_user(username=username, email=email, password='pw')


class OverdueDigestEmailTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Digest Org')
        self.team = Team.objects.create(organization=self.org, name='Digest Team')
        self.user = make_user('digestuser')
        self.todo = ToDo.objects.create(
            title='Overdue thing', owner=self.user, team=self.team,
            due_date=date.today() - timedelta(days=3),
        )

    def test_sends_email_with_todo_titles(self):
        sent = send_overdue_todo_digest(self.user, [self.todo])
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Overdue thing', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_skips_when_opted_out(self):
        pref = NotificationPreference.for_user(self.user)
        pref.overdue_todo_digest = False
        pref.save()
        sent = send_overdue_todo_digest(self.user, [self.todo])
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_when_no_email(self):
        self.user.email = ''
        self.user.save()
        sent = send_overdue_todo_digest(self.user, [self.todo])
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)


class MeetingReminderEmailTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Meeting Org')
        self.team = Team.objects.create(organization=self.org, name='Meeting Team')
        self.user = make_user('meetinguser')
        self.meeting = Meeting.objects.create(team=self.team, scheduled_date=date.today())

    def test_sends_email(self):
        sent = send_meeting_reminder(self.user, self.meeting)
        self.assertTrue(sent)
        self.assertIn('Meeting Team', mail.outbox[0].subject)

    def test_skips_when_opted_out(self):
        pref = NotificationPreference.for_user(self.user)
        pref.meeting_reminders = False
        pref.save()
        sent = send_meeting_reminder(self.user, self.meeting)
        self.assertFalse(sent)


class RockOffTrackEmailTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Rock Org')
        self.team = Team.objects.create(organization=self.org, name='Rock Team')
        self.owner = make_user('rockowner')
        self.rock = Rock.objects.create(
            title='Ship the thing', owner=self.owner, team=self.team,
            quarter=1, year=2026, due_date=date(2026, 3, 31),
            status=Rock.STATUS_OFF_TRACK,
        )

    def test_sends_to_owner(self):
        sent = send_rock_off_track_alert(self.rock)
        self.assertTrue(sent)
        self.assertEqual(mail.outbox[0].to, [self.owner.email])
        self.assertIn('Ship the thing', mail.outbox[0].subject)

    def test_skips_when_opted_out(self):
        pref = NotificationPreference.for_user(self.owner)
        pref.rock_off_track_alerts = False
        pref.save()
        sent = send_rock_off_track_alert(self.rock)
        self.assertFalse(sent)


class UserInviteEmailTest(TestCase):
    def test_sends_regardless_of_preference(self):
        org = Organization.objects.create(name='Invite Org')
        user = make_user('invitee')
        pref = NotificationPreference.for_user(user)
        pref.overdue_todo_digest = False
        pref.meeting_reminders = False
        pref.rock_off_track_alerts = False
        pref.save()

        sent = send_user_invite_email(user, org, 'https://example.com/reset/abc/def/')
        self.assertTrue(sent)
        self.assertIn('Invite Org', mail.outbox[0].body)
        self.assertIn('https://example.com/reset/abc/def/', mail.outbox[0].body)
