from django.test import TestCase
from django.contrib.auth.models import User
from apps.notifications.models import NotificationPreference


class NotificationPreferenceTest(TestCase):
    def test_created_automatically_for_new_user(self):
        user = User.objects.create_user(username='newuser', password='pw')
        self.assertTrue(NotificationPreference.objects.filter(user=user).exists())

    def test_defaults_to_all_enabled(self):
        user = User.objects.create_user(username='defaultuser', password='pw')
        pref = user.notification_preference
        self.assertTrue(pref.overdue_todo_digest)
        self.assertTrue(pref.meeting_reminders)
        self.assertTrue(pref.rock_off_track_alerts)

    def test_for_user_returns_existing(self):
        user = User.objects.create_user(username='existinguser', password='pw')
        pref = user.notification_preference
        self.assertEqual(NotificationPreference.for_user(user), pref)

    def test_for_user_creates_if_missing(self):
        user = User.objects.create_user(username='basicuser', password='pw')
        NotificationPreference.objects.filter(user=user).delete()
        pref = NotificationPreference.for_user(user)
        self.assertIsNotNone(pref.pk)

    def test_str(self):
        user = User.objects.create_user(username='struser', password='pw')
        self.assertIn('struser', str(user.notification_preference))
