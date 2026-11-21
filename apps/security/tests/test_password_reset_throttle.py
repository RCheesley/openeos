from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from apps.security.models import Throttle

RESET_URL = '/accounts/password_reset/'
DONE_URL = '/accounts/password_reset/done/'


@override_settings(
    PASSWORD_RESET_ADDRESS_LIMIT=0, PASSWORD_RESET_EMAIL_LIMIT=2,
    PASSWORD_RESET_WINDOW_SECONDS=3600, TRUSTED_PROXY_COUNT=0,
)
class PasswordResetThrottleTest(TestCase):
    def setUp(self):
        User.objects.create_user(username='skipper', email='skipper@example.com', password='pw')

    def ask(self, email='skipper@example.com', address='127.0.0.1'):
        return self.client.post(RESET_URL, {'email': email}, REMOTE_ADDR=address)

    def test_emails_to_one_address_are_capped(self):
        for _ in range(5):
            response = self.ask()
            self.assertRedirects(response, DONE_URL)
        self.assertEqual(len(mail.outbox), 2)

    def test_cap_ignores_case_and_follows_the_email_not_the_sender(self):
        self.ask('Skipper@Example.com', address='203.0.113.1')
        self.ask('skipper@example.com', address='203.0.113.2')
        self.ask('SKIPPER@example.com', address='203.0.113.3')
        self.assertEqual(len(mail.outbox), 2)

    def test_cap_is_lifted_after_the_window(self):
        for _ in range(3):
            self.ask()
        Throttle.objects.update(
            throttling_failure_timestamp=Throttle.objects.get().throttling_failure_timestamp
            - timedelta(seconds=3601),
        )
        self.ask()
        self.assertEqual(len(mail.outbox), 3)

    def test_response_is_the_same_for_known_and_unknown_emails(self):
        for _ in range(4):
            known = self.ask('skipper@example.com')
            unknown = self.ask('nobody@example.com')
            self.assertEqual(known.status_code, unknown.status_code)
            self.assertEqual(known['Location'], unknown['Location'])
        # Both are counted, so the table does not show which one has an account.
        counts = Throttle.objects.values_list('throttling_failure_count', flat=True)
        self.assertEqual(list(counts), [2, 2])

    @override_settings(PASSWORD_RESET_ADDRESS_LIMIT=3, PASSWORD_RESET_EMAIL_LIMIT=0)
    def test_requests_from_one_address_are_limited(self):
        for n in range(3):
            self.assertRedirects(self.ask(f'person{n}@example.com'), DONE_URL)
        for email in ('skipper@example.com', 'nobody@example.com'):
            response = self.ask(email)
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                'Too many password reset requests. Please wait 60 minutes before trying again.',
            )
        self.assertEqual(len(mail.outbox), 0)
        # Another address is still served.
        self.assertRedirects(self.ask(address='203.0.113.9'), DONE_URL)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(PASSWORD_RESET_ADDRESS_LIMIT=0, PASSWORD_RESET_EMAIL_LIMIT=0)
    def test_limits_of_zero_switch_throttling_off(self):
        for _ in range(6):
            self.ask()
        self.assertEqual(len(mail.outbox), 6)
        self.assertFalse(Throttle.objects.exists())
