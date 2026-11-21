import time
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Membership, Organization, Team
from apps.audit.models import AuditEvent
from apps.meetings.models import Meeting
from apps.security.middleware import SESSION_LAST_ACTIVITY, keepalive_interval_seconds

MINUTE = 60


@override_settings(SESSION_IDLE_TIMEOUT_MINUTES=30)
class IdleTimeoutTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights')
        self.team = Team.objects.create(organization=self.org, name='Leadership')
        self.user = User.objects.create_user(username='skipper', password='right-pw')
        Membership.objects.create(
            user=self.user, organization=self.org, role=Membership.ROLE_ADMIN,
        )
        self.user.profile.teams.add(self.team)
        self.client.force_login(self.user)

    def idle_for(self, seconds):
        session = self.client.session
        session[SESSION_LAST_ACTIVITY] = time.time() - seconds
        session.save()

    def last_activity(self):
        return self.client.session.get(SESSION_LAST_ACTIVITY)

    def signed_in(self):
        return '_auth_user_id' in self.client.session

    def running_meeting(self, started_ago=timedelta(minutes=50)):
        meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date(2026, 1, 5), created_by=self.user,
        )
        meeting.start()
        Meeting.objects.filter(pk=meeting.pk).update(started_at=timezone.now() - started_ago)
        return meeting

    def test_first_request_starts_the_clock(self):
        self.assertIsNone(self.last_activity())
        self.assertEqual(self.client.get('/rocks/').status_code, 200)
        self.assertAlmostEqual(self.last_activity(), time.time(), delta=5)

    def test_active_session_carries_on_and_is_refreshed(self):
        self.idle_for(29 * MINUTE)
        self.assertEqual(self.client.get('/rocks/').status_code, 200)
        self.assertTrue(self.signed_in())
        self.assertAlmostEqual(self.last_activity(), time.time(), delta=5)

    def test_activity_within_the_last_minute_is_not_written_again(self):
        self.idle_for(20)
        before = self.last_activity()
        self.client.get('/rocks/')
        self.assertEqual(self.last_activity(), before)

    def test_idle_session_is_signed_out_and_returned_to_the_same_page(self):
        self.idle_for(32 * MINUTE)
        response = self.client.get('/rocks/?status=on_track')
        self.assertRedirects(
            response, '/accounts/login/?next=/rocks/%3Fstatus%3Don_track',
            fetch_redirect_response=False,
        )
        self.assertFalse(self.signed_in())
        page = self.client.get(response['Location'])
        self.assertContains(page, 'You were signed out after a period without activity.')
        back = self.client.post('/accounts/login/', {
            'username': 'skipper', 'password': 'right-pw', 'next': '/rocks/?status=on_track',
        })
        self.assertRedirects(back, '/rocks/?status=on_track', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/rocks/?status=on_track').status_code, 200)

    def test_expired_form_post_returns_to_the_page_it_came_from(self):
        meeting = self.running_meeting()
        self.idle_for(32 * MINUTE)
        response = self.client.post(
            f'/meetings/{meeting.pk}/advance/',
            HTTP_REFERER=f'http://testserver/meetings/{meeting.pk}/?tab=notes',
        )
        self.assertRedirects(
            response, f'/accounts/login/?next=/meetings/{meeting.pk}/%3Ftab%3Dnotes',
            fetch_redirect_response=False,
        )
        meeting.refresh_from_db()
        self.assertEqual(meeting.current_segment, 0)

    def test_expired_form_post_ignores_a_referer_on_another_site(self):
        self.idle_for(32 * MINUTE)
        response = self.client.post('/todos/new/', HTTP_REFERER='https://elsewhere.example/x')
        self.assertRedirects(
            response, '/accounts/login/?next=/', fetch_redirect_response=False,
        )

    def test_expiry_is_audited(self):
        self.idle_for(32 * MINUTE)
        self.client.get('/rocks/')
        event = AuditEvent.objects.get(action='user.session_expired')
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.details, {'idle_minutes': 30})

    def test_expired_user_opening_the_sign_in_page_just_sees_it(self):
        self.idle_for(32 * MINUTE)
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.signed_in())

    @override_settings(SESSION_IDLE_TIMEOUT_MINUTES=0)
    def test_zero_switches_the_timeout_off(self):
        self.idle_for(10 * 24 * 60 * MINUTE)
        before = self.last_activity()
        self.assertEqual(self.client.get('/rocks/').status_code, 200)
        self.assertTrue(self.signed_in())
        self.assertEqual(self.last_activity(), before)
        self.assertEqual(keepalive_interval_seconds(), 0)

    # ── The Weekly Meeting runner ────────────────────────────────────────────

    def test_runner_page_reports_in_while_the_meeting_runs(self):
        meeting = self.running_meeting()
        response = self.client.get(f'/meetings/{meeting.pk}/')
        self.assertContains(response, 'session-keepalive')
        self.assertContains(response, f'data-keepalive-url="/meetings/{meeting.pk}/keepalive/"')
        self.assertContains(response, 'data-keepalive-seconds="300"')

    def test_runner_page_does_not_report_in_before_the_meeting_starts(self):
        meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date(2026, 1, 5), created_by=self.user,
        )
        self.assertNotContains(self.client.get(f'/meetings/{meeting.pk}/'), 'session-keepalive')

    @override_settings(SESSION_IDLE_TIMEOUT_MINUTES=0)
    def test_runner_page_does_not_report_in_when_the_timeout_is_off(self):
        meeting = self.running_meeting()
        self.assertNotContains(self.client.get(f'/meetings/{meeting.pk}/'), 'session-keepalive')

    def test_keepalive_interval_fits_inside_the_timeout(self):
        self.assertEqual(keepalive_interval_seconds(), 300)
        with override_settings(SESSION_IDLE_TIMEOUT_MINUTES=5):
            self.assertEqual(keepalive_interval_seconds(), 100)
        with override_settings(SESSION_IDLE_TIMEOUT_MINUTES=1):
            self.assertEqual(keepalive_interval_seconds(), 30)

    def test_facilitator_on_one_page_for_ninety_minutes_stays_signed_in(self):
        meeting = self.running_meeting(started_ago=timedelta(0))
        # Eighteen five-minute reports, each arriving after 5 minutes of no other request.
        for _ in range(18):
            self.idle_for(5 * MINUTE)
            response = self.client.post(f'/meetings/{meeting.pk}/keepalive/')
            self.assertEqual(response.json(), {'active': True})
            self.assertAlmostEqual(self.last_activity(), time.time(), delta=5)
        self.assertEqual(self.client.post(f'/meetings/{meeting.pk}/advance/').status_code, 302)
        self.assertTrue(self.signed_in())

    def test_keepalive_for_a_meeting_that_is_not_running_is_not_activity(self):
        meeting = Meeting.objects.create(
            team=self.team, scheduled_date=date(2026, 1, 5), created_by=self.user,
        )
        self.idle_for(20 * MINUTE)
        before = self.last_activity()
        response = self.client.post(f'/meetings/{meeting.pk}/keepalive/')
        self.assertEqual(response.json(), {'active': False})
        self.assertEqual(self.last_activity(), before)

    def test_keepalive_stops_counting_for_a_meeting_left_running(self):
        meeting = self.running_meeting(started_ago=timedelta(hours=5))
        self.idle_for(20 * MINUTE)
        before = self.last_activity()
        response = self.client.post(f'/meetings/{meeting.pk}/keepalive/')
        self.assertEqual(response.json(), {'active': False})
        self.assertEqual(self.last_activity(), before)

    def test_keepalive_cannot_revive_an_expired_session(self):
        meeting = self.running_meeting()
        self.idle_for(32 * MINUTE)
        response = self.client.post(f'/meetings/{meeting.pk}/keepalive/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.signed_in())

    def test_keepalive_needs_a_post(self):
        meeting = self.running_meeting()
        self.assertEqual(self.client.get(f'/meetings/{meeting.pk}/keepalive/').status_code, 405)
