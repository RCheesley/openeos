from django.test import TestCase
from django.contrib.auth.models import User

from apps.notifications.models import NotificationPreference


class NotificationPreferenceViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='prefuser', password='pw')
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get('/notifications/preferences/')
        self.assertEqual(resp.status_code, 302)

    def test_get_renders_form(self):
        resp = self.client.get('/notifications/preferences/')
        self.assertEqual(resp.status_code, 200)

    def test_post_updates_preferences(self):
        resp = self.client.post('/notifications/preferences/', {
            'meeting_reminders': 'on',
            # overdue_todo_digest and rock_off_track_alerts omitted → unchecked
        })
        self.assertEqual(resp.status_code, 302)
        pref = NotificationPreference.for_user(self.user)
        self.assertFalse(pref.overdue_todo_digest)
        self.assertTrue(pref.meeting_reminders)
        self.assertFalse(pref.rock_off_track_alerts)
