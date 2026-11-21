from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Membership, Organization
from apps.accounts.two_factor.forms import too_many_attempts_message
from apps.audit.models import AuditEvent
from apps.security.addresses import address_bucket, client_address
from apps.security.models import Throttle

LOGIN_URL = '/accounts/login/'
HOME = '127.0.0.1'
ELSEWHERE = '203.0.113.9'

LIMITS = {
    'SIGN_IN_FAILURE_LIMIT': 3,
    'SIGN_IN_ADDRESS_FAILURE_LIMIT': 0,
    'SIGN_IN_LOCKOUT_SECONDS': 60,
    'SIGN_IN_LOCKOUT_MAX_SECONDS': 200,
    'SIGN_IN_FAILURE_WINDOW_SECONDS': 900,
    'TRUSTED_PROXY_COUNT': 0,
}


def age_counters(seconds):
    """Move every counter into the past, as if that much time had gone by."""
    for throttle in Throttle.objects.all():
        Throttle.objects.filter(pk=throttle.pk).update(
            throttling_failure_timestamp=throttle.throttling_failure_timestamp
            - timedelta(seconds=seconds),
        )


@override_settings(**LIMITS)
class SignInThrottleTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights')
        self.user = User.objects.create_user(username='skipper', password='right-pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Membership.ROLE_ADMIN,
        )

    def attempt(self, username='skipper', password='wrong', address=HOME, url=LOGIN_URL):
        return self.client.post(
            url, {'username': username, 'password': password}, REMOTE_ADDR=address,
        )

    def fail(self, times, **kwargs):
        response = None
        for _ in range(times):
            response = self.attempt(**kwargs)
        return response

    def signed_in(self):
        return '_auth_user_id' in self.client.session

    def error(self, response):
        return response.context['form'].non_field_errors()

    def test_failures_below_the_limit_do_not_lock(self):
        response = self.fail(2)
        self.assertContains(response, 'Invalid username or password')
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)
        self.assertTrue(self.signed_in())

    def test_lock_out_after_the_limit(self):
        response = self.fail(3)
        self.assertEqual(self.error(response), [too_many_attempts_message(60)])
        self.assertContains(response, 'Please wait 60 seconds before trying again.')
        self.assertNotContains(response, 'Invalid username or password')

    def test_correct_password_is_refused_during_lock_out(self):
        self.fail(3)
        response = self.attempt(password='right-pw')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.signed_in())
        self.assertContains(response, 'Too many failed attempts.')

    def test_refused_attempts_do_not_lengthen_the_lock_out(self):
        self.fail(3)
        self.fail(4, password='right-pw')
        throttle = Throttle.objects.get(scope=Throttle.SCOPE_SIGN_IN_ACCOUNT)
        self.assertEqual(throttle.throttling_failure_count, 3)

    def test_lock_out_is_released_after_its_time(self):
        self.fail(3)
        age_counters(61)
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)
        self.assertTrue(self.signed_in())

    def test_lock_out_grows_with_repeated_failures_up_to_the_maximum(self):
        self.fail(3)
        age_counters(61)
        self.assertEqual(self.error(self.attempt()), [too_many_attempts_message(120)])
        age_counters(121)
        # 240 seconds would be next; the maximum is 200.
        self.assertEqual(self.error(self.attempt()), [too_many_attempts_message(200)])
        age_counters(199)
        self.assertFalse(self.attempt(password='right-pw').status_code == 302)
        age_counters(2)
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)

    def test_success_resets_the_counter(self):
        self.fail(2)
        self.attempt(password='right-pw')
        self.assertFalse(Throttle.objects.exists())
        self.client.logout()
        response = self.fail(2)
        self.assertContains(response, 'Invalid username or password')
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)

    def test_failures_are_forgotten_after_the_window(self):
        self.fail(2)
        age_counters(901)
        response = self.attempt()
        self.assertContains(response, 'Invalid username or password')
        self.assertEqual(Throttle.objects.get().throttling_failure_count, 1)

    def test_messages_are_identical_for_existing_and_unknown_accounts(self):
        known = [self.attempt(username='skipper') for _ in range(4)]
        unknown = [self.attempt(username='nobody-here') for _ in range(4)]
        for real, ghost in zip(known, unknown):
            self.assertEqual(real.status_code, ghost.status_code)
            self.assertEqual(self.error(real), self.error(ghost))
            self.assertEqual(
                real.context['form'].throttled, ghost.context['form'].throttled,
            )
        self.assertTrue(known[-1].context['form'].throttled)

    def test_username_case_and_spacing_share_one_counter(self):
        self.attempt(username='Skipper')
        self.attempt(username='SKIPPER')
        response = self.attempt(username='skipper')
        self.assertTrue(response.context['form'].throttled)

    def test_counter_rows_hold_no_username_or_address(self):
        self.fail(1)
        for throttle in Throttle.objects.all():
            self.assertNotIn('skipper', throttle.key)
            self.assertNotIn(HOME, throttle.key)
            self.assertEqual(len(throttle.key), 64)

    @override_settings(SIGN_IN_FAILURE_LIMIT=0, SIGN_IN_ADDRESS_FAILURE_LIMIT=3)
    def test_address_limit_counts_across_usernames(self):
        for name in ('ann', 'bob', 'cat'):
            response = self.attempt(username=name)
        self.assertTrue(response.context['form'].throttled)
        # The address is locked whichever account is tried next, with any password.
        self.assertEqual(self.attempt(password='right-pw').status_code, 200)
        self.assertFalse(self.signed_in())
        # Someone else, somewhere else, is not affected.
        self.assertEqual(self.attempt(password='right-pw', address=ELSEWHERE).status_code, 302)

    @override_settings(SIGN_IN_ADDRESS_FAILURE_LIMIT=4)
    def test_signing_in_does_not_clear_the_address_count(self):
        self.fail(2, username='ann')
        self.attempt(password='right-pw')
        self.client.logout()
        self.fail(1, username='bob')
        response = self.attempt(username='cat')
        self.assertTrue(response.context['form'].throttled)

    def test_lock_out_writes_one_audit_event(self):
        self.fail(2)
        self.assertFalse(AuditEvent.objects.filter(action='user.sign_in_locked').exists())
        self.fail(1)
        self.fail(3, password='right-pw')
        event = AuditEvent.objects.get(action='user.sign_in_locked')
        self.assertEqual(event.organization, self.org)
        self.assertIsNone(event.actor)
        self.assertEqual(event.ip_address, HOME)
        self.assertEqual(event.details, {
            'username': 'skipper', 'limit': 'account', 'failures': 3, 'seconds': 60,
        })

    def test_lock_out_of_an_unknown_username_is_audited_without_an_organisation(self):
        self.fail(3, username='nobody-here')
        event = AuditEvent.objects.get(action='user.sign_in_locked')
        self.assertIsNone(event.organization)

    def test_django_admin_sign_in_is_limited_too(self):
        self.user.is_staff = True
        self.user.save()
        self.fail(3, url='/admin/login/')
        response = self.attempt(password='right-pw', url='/admin/login/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.signed_in())

    def test_clean_sign_in_costs_one_read_and_no_write(self):
        with CaptureQueriesContext(connection) as queries:
            self.attempt(password='right-pw')
        touching = [q['sql'] for q in queries if 'security_throttle' in q['sql']]
        self.assertEqual(len(touching), 1)
        self.assertTrue(touching[0].startswith('SELECT'))

    @override_settings(SIGN_IN_FAILURE_LIMIT=0, SIGN_IN_ADDRESS_FAILURE_LIMIT=0)
    def test_limits_of_zero_switch_throttling_off(self):
        with CaptureQueriesContext(connection) as queries:
            self.fail(10)
        self.assertFalse([q for q in queries if 'security_throttle' in q['sql']])
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)

    @override_settings(SIGN_IN_ADDRESS_FAILURE_LIMIT=3, SIGN_IN_LOCKOUT_SECONDS=0)
    def test_lockout_seconds_of_zero_switches_throttling_off(self):
        self.fail(10)
        self.assertFalse(Throttle.objects.exists())
        self.assertEqual(self.attempt(password='right-pw').status_code, 302)

    def test_old_counters_are_cleared_when_a_new_failure_is_counted(self):
        self.fail(1, username='long-ago')
        age_counters(2 * 24 * 60 * 60)
        self.fail(1)
        self.assertEqual(Throttle.objects.count(), 1)


class MessageTest(TestCase):
    def test_short_waits_in_seconds_and_long_waits_in_minutes(self):
        self.assertIn('wait 1 second before', too_many_attempts_message(1))
        self.assertIn('wait 60 seconds before', too_many_attempts_message(60))
        self.assertIn('wait 2 minutes before', too_many_attempts_message(120))
        self.assertIn('wait 3 minutes before', too_many_attempts_message(121))
        self.assertIn('wait 60 minutes before', too_many_attempts_message(3600))


class ClientAddressTest(TestCase):
    def request(self, forwarded=None, remote='10.0.0.5'):
        extra = {'REMOTE_ADDR': remote}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return RequestFactory().get('/', **extra)

    @override_settings(TRUSTED_PROXY_COUNT=None, SECURE_PROXY_SSL_HEADER=None)
    def test_header_is_ignored_without_a_trusted_proxy(self):
        self.assertEqual(client_address(self.request('198.51.100.7')), '10.0.0.5')

    @override_settings(
        TRUSTED_PROXY_COUNT=None, SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    )
    def test_header_is_honoured_when_the_proxy_setting_is_present(self):
        self.assertEqual(client_address(self.request('198.51.100.7')), '198.51.100.7')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_only_the_entry_added_by_the_proxy_is_believed(self):
        # Nginx appends the address it saw; anything before that came from the client.
        request = self.request('1.2.3.4, 198.51.100.7')
        self.assertEqual(client_address(request), '198.51.100.7')

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies(self):
        request = self.request('1.2.3.4, 198.51.100.7, 172.18.0.3')
        self.assertEqual(client_address(request), '198.51.100.7')
        self.assertEqual(client_address(self.request('198.51.100.7')), '198.51.100.7')

    @override_settings(
        TRUSTED_PROXY_COUNT=0, SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    )
    def test_explicit_zero_overrides_the_proxy_setting(self):
        self.assertEqual(client_address(self.request('198.51.100.7')), '10.0.0.5')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_missing_or_unreadable_header_falls_back_to_the_connection(self):
        self.assertEqual(client_address(self.request()), '10.0.0.5')
        self.assertEqual(client_address(self.request('not-an-address')), '10.0.0.5')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_ipv6_addresses_are_counted_by_their_64(self):
        first = address_bucket(self.request(remote='2001:db8:1:2:aaaa::1'))
        second = address_bucket(self.request(remote='2001:db8:1:2:bbbb::2'))
        other = address_bucket(self.request(remote='2001:db8:1:3::1'))
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(address_bucket(self.request(remote='::ffff:10.0.0.5')), '10.0.0.5')


@override_settings(**{**LIMITS, 'SIGN_IN_FAILURE_LIMIT': 0, 'SIGN_IN_ADDRESS_FAILURE_LIMIT': 2})
class ProxyAddressThrottleTest(TestCase):
    """The address limit follows the forwarded address only behind a trusted proxy."""

    def attempt(self, forwarded):
        return self.client.post(
            LOGIN_URL, {'username': 'x', 'password': 'y'},
            REMOTE_ADDR='172.18.0.3', HTTP_X_FORWARDED_FOR=forwarded,
        )

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_trusted_proxy_separates_clients(self):
        self.attempt('198.51.100.7')
        self.attempt('198.51.100.7')
        self.assertFalse(self.attempt('198.51.100.8').context['form'].throttled)
        self.assertTrue(self.attempt('198.51.100.7').context['form'].throttled)

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_a_made_up_first_entry_does_not_dodge_the_limit(self):
        self.attempt('1.1.1.1, 198.51.100.7')
        self.attempt('2.2.2.2, 198.51.100.7')
        self.assertTrue(self.attempt('3.3.3.3, 198.51.100.7').context['form'].throttled)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_untrusted_header_cannot_dodge_the_limit(self):
        self.attempt('198.51.100.7')
        self.attempt('198.51.100.8')
        self.assertTrue(self.attempt('198.51.100.9').context['form'].throttled)
