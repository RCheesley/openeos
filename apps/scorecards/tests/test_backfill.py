from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.audit.models import AuditEvent
from apps.scorecards.models import (
    Scorecard, ScorecardEntry, ScorecardMetric, build_periods, period_label, period_start_for, shift_period,
)

WEEKLY = ScorecardMetric.FREQ_WEEKLY
MONTHLY = ScorecardMetric.FREQ_MONTHLY


class BackfillBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Backfill Org')
        self.team = Team.objects.create(organization=self.org, name='Backfill Team')
        self.user = self.member('priya', 'Priya', 'Owner', Membership.ROLE_ADMIN)
        self.scorecard = Scorecard.objects.create(name='Harbour numbers', team=self.team)
        self.weekly = self.metric('Berths occupied')
        self.monthly = self.metric('Fuel sold', MONTHLY)
        self.weeks = build_periods(WEEKLY)
        self.months = build_periods(MONTHLY)
        self.client.force_login(self.user)

    def member(self, username, first, last, role=Membership.ROLE_MEMBER):
        user = User.objects.create_user(username=username, password='pw', first_name=first, last_name=last)
        Membership.objects.create(user=user, organization=self.org, role=role)
        user.profile.teams.add(self.team)
        return user

    def metric(self, name, frequency=WEEKLY):
        return ScorecardMetric.objects.create(
            scorecard=self.scorecard, name=name, owner=self.user,
            metric_type=ScorecardMetric.TYPE_INTEGER, goal_value=Decimal('10'),
            goal_direction=ScorecardMetric.DIR_ABOVE, frequency=frequency,
        )

    def url(self, frequency, period, metric=None):
        url = f'/scorecards/{self.scorecard.pk}/enter/?frequency={frequency}&period={period.isoformat()}'
        return f'{url}&metric={metric.pk}' if metric else url


class BoardLinksTest(BackfillBase):
    def test_every_cell_and_column_heading_links_to_its_period(self):
        ScorecardEntry.objects.create(
            metric=self.weekly, period_start=self.weeks[3], value=Decimal('12'),
            notes='Regatta week', entered_by=self.user,
        )
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        base = f'/scorecards/{self.scorecard.pk}/enter/'
        for frequency, period, metric in (
            (WEEKLY, self.weeks[3], self.weekly), (WEEKLY, self.weeks[0], self.weekly),
            (MONTHLY, self.months[5], self.monthly),
        ):
            query = f'?frequency={frequency}&amp;period={period.isoformat()}'
            self.assertContains(resp, f'href="{base}{query}"', count=1)
            self.assertContains(resp, f'href="{base}{query}&amp;metric={metric.pk}"', count=1)
        self.assertContains(resp, 'Entered by Priya Owner')
        self.assertContains(resp, 'Regatta week')
        self.assertContains(
            resp, f'aria-label="Enter Berths occupied for the period starting {self.weeks[0].day} ',
        )


class EnterEarlierPeriodTest(BackfillBase):
    def test_form_names_the_earlier_period_and_lists_only_that_cadence(self):
        resp = self.client.get(self.url(WEEKLY, self.weeks[2]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, period_label(WEEKLY, self.weeks[2]))
        self.assertContains(resp, 'You are entering values for an earlier period')
        self.assertEqual([r['metric'] for r in resp.context['rows']], [self.weekly])

    def test_current_period_form_does_not_carry_the_earlier_period_note(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/enter/')
        self.assertNotContains(resp, 'You are entering values for an earlier period')
        self.assertEqual(len(resp.context['rows']), 2)

    def test_entering_an_earlier_week(self):
        resp = self.client.post(
            self.url(WEEKLY, self.weeks[2]),
            {f'value_{self.weekly.pk}': '8', f'notes_{self.weekly.pk}': 'Storm closure'}, follow=True,
        )
        self.assertRedirects(resp, f'/scorecards/{self.scorecard.pk}/')
        entry = ScorecardEntry.objects.get(metric=self.weekly)
        self.assertEqual(entry.period_start, self.weeks[2])
        self.assertEqual(entry.period_start.weekday(), 0)
        self.assertEqual(entry.value, Decimal('8'))
        self.assertFalse(entry.on_track)
        self.assertEqual(entry.notes, 'Storm closure')
        self.assertEqual(entry.entered_by, self.user)
        self.assertIsNotNone(entry.entered_at)
        self.assertContains(resp, f'1 metric updated for week of {self.weeks[2]}.')
        # A first entry is not a correction, so nothing is logged.
        self.assertFalse(AuditEvent.objects.filter(action='scorecard.entry_changed').exists())

    def test_entering_an_earlier_month(self):
        self.client.post(self.url(MONTHLY, self.months[1]), {f'value_{self.monthly.pk}': '15'})
        entry = ScorecardEntry.objects.get(metric=self.monthly)
        self.assertEqual(entry.period_start, self.months[1])
        self.assertTrue(entry.on_track)

    def test_one_metric_form_shows_and_saves_only_that_metric(self):
        other = self.metric('Visitor nights')
        url = self.url(WEEKLY, self.weeks[5], self.weekly)
        self.assertEqual([r['metric'] for r in self.client.get(url).context['rows']], [self.weekly])
        self.client.post(url, {f'value_{self.weekly.pk}': '10', f'value_{other.pk}': '99'})
        self.assertEqual(ScorecardEntry.objects.get().metric, self.weekly)

    def test_invalid_number_is_reported_and_nothing_saved(self):
        resp = self.client.post(self.url(WEEKLY, self.weeks[2]), {f'value_{self.weekly.pk}': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid number.')
        self.assertFalse(ScorecardEntry.objects.exists())


class CorrectEarlierPeriodTest(BackfillBase):
    def setUp(self):
        super().setUp()
        self.colleague = self.member('sam', 'Sam', 'Mate')
        self.entry = ScorecardEntry.objects.create(
            metric=self.weekly, period_start=self.weeks[4], value=Decimal('12'),
            notes='First count', entered_by=self.colleague,
        )
        self.url_ = self.url(WEEKLY, self.weeks[4], self.weekly)

    def test_form_shows_the_stored_value_and_who_entered_it(self):
        resp = self.client.get(self.url_)
        self.assertContains(resp, 'value="12.0000"')
        self.assertContains(resp, 'value="First count"')
        self.assertContains(resp, 'Sam Mate, ')

    def test_correction_overwrites_the_entry_and_logs_the_previous_value(self):
        created_at = self.entry.created_at
        self.client.post(self.url_, {f'value_{self.weekly.pk}': '7', f'notes_{self.weekly.pk}': 'Recount'})
        entry = ScorecardEntry.objects.get(metric=self.weekly)
        self.assertEqual(entry.pk, self.entry.pk)
        self.assertEqual(entry.period_start, self.weeks[4])
        self.assertEqual(entry.value, Decimal('7'))
        self.assertFalse(entry.on_track)
        self.assertEqual(entry.notes, 'Recount')
        self.assertEqual(entry.entered_by, self.user)
        self.assertEqual(entry.created_at, created_at)
        self.assertGreater(entry.updated_at, created_at)
        self.assertEqual(entry.entered_at, entry.updated_at)

        event = AuditEvent.objects.get(action='scorecard.entry_changed')
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.target_id, str(entry.pk))
        self.assertEqual(event.details['previous_value'], '12.0000')
        self.assertEqual(event.details['previous_notes'], 'First count')
        self.assertEqual(event.details['new_value'], '7')
        self.assertEqual(event.details['new_notes'], 'Recount')
        self.assertEqual(event.details['metric'], 'Berths occupied')
        self.assertEqual(event.details['period'], period_label(WEEKLY, self.weeks[4]))

    def test_saving_without_a_change_keeps_who_entered_it(self):
        updated_at = ScorecardEntry.objects.get(pk=self.entry.pk).updated_at
        resp = self.client.post(
            self.url_, {f'value_{self.weekly.pk}': '12.0000', f'notes_{self.weekly.pk}': 'First count'},
            follow=True,
        )
        entry = ScorecardEntry.objects.get(pk=self.entry.pk)
        self.assertEqual(entry.entered_by, self.colleague)
        self.assertEqual(entry.updated_at, updated_at)
        self.assertFalse(AuditEvent.objects.filter(action='scorecard.entry_changed').exists())
        self.assertContains(resp, '0 metrics updated')

    def test_blank_value_keeps_the_entry(self):
        self.client.post(self.url_, {f'value_{self.weekly.pk}': ''})
        self.assertEqual(ScorecardEntry.objects.get(pk=self.entry.pk).value, Decimal('12'))

    def test_correcting_the_current_week_is_logged_too(self):
        current = ScorecardEntry.objects.create(
            metric=self.weekly, period_start=self.weeks[-1], value=Decimal('3'), entered_by=self.colleague,
        )
        self.client.post(f'/scorecards/{self.scorecard.pk}/enter/', {f'value_{self.weekly.pk}': '4'})
        current.refresh_from_db()
        self.assertEqual(current.value, Decimal('4'))
        self.assertEqual(AuditEvent.objects.get(action='scorecard.entry_changed').details['previous_value'], '3.0000')

    def test_monthly_value_stored_on_a_monday_is_corrected_where_it_is(self):
        month = self.months[6]
        monday = period_start_for(WEEKLY, month + timedelta(days=17))
        legacy = ScorecardEntry.objects.create(
            metric=self.monthly, period_start=monday, value=Decimal('5'), entered_by=self.colleague,
        )
        self.client.post(self.url(MONTHLY, month, self.monthly), {f'value_{self.monthly.pk}': '20'})
        legacy.refresh_from_db()
        self.assertEqual(legacy.value, Decimal('20'))
        self.assertEqual(legacy.period_start, monday)
        self.assertEqual(ScorecardEntry.objects.filter(metric=self.monthly).count(), 1)


class BackfillLimitsTest(BackfillBase):
    """Only the 13 periods on the board, and only for people who can enter current values."""

    def assert_not_found(self, url):
        self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(url, {f'value_{self.weekly.pk}': '5'}).status_code, 404, url)
        self.assertFalse(ScorecardEntry.objects.exists())

    def test_period_older_than_the_board_is_refused(self):
        self.assert_not_found(self.url(WEEKLY, shift_period(WEEKLY, self.weeks[0], -1)))
        self.assert_not_found(self.url(MONTHLY, shift_period(MONTHLY, self.months[0], -1)))

    def test_future_period_is_refused(self):
        self.assert_not_found(self.url(WEEKLY, shift_period(WEEKLY, self.weeks[-1], 1)))

    def test_date_that_is_not_a_period_start_is_refused(self):
        self.assert_not_found(self.url(WEEKLY, self.weeks[3] + timedelta(days=1)))
        self.assert_not_found(self.url(MONTHLY, self.months[3] + timedelta(days=1)))

    def test_malformed_requests_are_refused(self):
        base = f'/scorecards/{self.scorecard.pk}/enter/'
        for query in (
            '?frequency=weekly', '?period=' + self.weeks[3].isoformat(),
            '?frequency=daily&period=' + self.weeks[3].isoformat(), '?frequency=weekly&period=yesterday',
        ):
            self.assert_not_found(base + query)

    def test_metric_of_another_cadence_or_board_is_refused(self):
        self.assert_not_found(self.url(WEEKLY, self.weeks[3], self.monthly))
        other_board = Scorecard.objects.create(name='Other board', team=self.team)
        stray = ScorecardMetric.objects.create(
            scorecard=other_board, name='Stray', owner=self.user, goal_value=Decimal('1'),
        )
        self.assert_not_found(self.url(WEEKLY, self.weeks[3], stray))

    def test_cadence_with_no_metrics_is_refused(self):
        self.assert_not_found(self.url(ScorecardMetric.FREQ_QUARTERLY, build_periods('quarterly')[0]))

    def test_login_is_required(self):
        self.client.logout()
        for url in (f'/scorecards/{self.scorecard.pk}/enter/', self.url(WEEKLY, self.weeks[3])):
            resp = self.client.post(url, {f'value_{self.weekly.pk}': '5'})
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(resp.url.startswith('/accounts/login/'))
        self.assertFalse(ScorecardEntry.objects.exists())

    def test_a_member_who_can_enter_this_week_can_enter_an_earlier_week(self):
        self.client.force_login(self.member('sam', 'Sam', 'Mate'))
        current = self.client.post(f'/scorecards/{self.scorecard.pk}/enter/', {f'value_{self.weekly.pk}': '5'})
        earlier = self.client.post(self.url(WEEKLY, self.weeks[3]), {f'value_{self.weekly.pk}': '6'})
        self.assertEqual((current.status_code, earlier.status_code), (302, 302))
        self.assertEqual(ScorecardEntry.objects.count(), 2)

    def test_someone_from_another_organisation_can_enter_neither(self):
        other_org = Organization.objects.create(name='Elsewhere')
        outsider = User.objects.create_user(username='outsider', password='pw')
        Membership.objects.create(user=outsider, organization=other_org, role=Membership.ROLE_ADMIN)
        self.client.force_login(outsider)
        self.assert_not_found(f'/scorecards/{self.scorecard.pk}/enter/')
        self.assert_not_found(self.url(WEEKLY, self.weeks[3]))
        self.assert_not_found(self.url(MONTHLY, self.months[3], self.monthly))
