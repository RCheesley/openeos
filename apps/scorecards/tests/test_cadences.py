import csv
import io
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.scorecards.models import (
    Scorecard, ScorecardEntry, ScorecardMetric,
    build_periods, period_column_label, period_label, period_start_for, shift_period,
)

WEEKLY = ScorecardMetric.FREQ_WEEKLY
MONTHLY = ScorecardMetric.FREQ_MONTHLY
QUARTERLY = ScorecardMetric.FREQ_QUARTERLY
ANNUAL = ScorecardMetric.FREQ_ANNUAL


class PeriodBuildingTest(SimpleTestCase):
    """Thirteen periods per cadence, across month and year boundaries."""

    def test_weekly_periods_are_mondays_across_a_year_boundary(self):
        # Friday 1 January 2027 belongs to the week of Monday 28 December 2026.
        periods = build_periods(WEEKLY, today=date(2027, 1, 1))
        self.assertEqual(len(periods), 13)
        self.assertEqual(periods[-1], date(2026, 12, 28))
        self.assertEqual(periods[0], date(2026, 10, 5))
        self.assertTrue(all(p.weekday() == 0 for p in periods))
        self.assertTrue(all(b - a == timedelta(weeks=1) for a, b in zip(periods, periods[1:])))

    def test_weekly_period_for_a_monday_is_that_monday(self):
        self.assertEqual(period_start_for(WEEKLY, date(2026, 11, 16)), date(2026, 11, 16))
        self.assertEqual(period_start_for(WEEKLY, date(2026, 11, 22)), date(2026, 11, 16))

    def test_monthly_periods_across_a_year_boundary(self):
        periods = build_periods(MONTHLY, today=date(2027, 2, 14))
        self.assertEqual(len(periods), 13)
        self.assertEqual(periods[0], date(2026, 2, 1))
        self.assertEqual(periods[-1], date(2027, 2, 1))
        self.assertEqual(periods[10:], [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)])

    def test_monthly_period_on_the_last_day_of_a_month(self):
        self.assertEqual(period_start_for(MONTHLY, date(2028, 2, 29)), date(2028, 2, 1))
        self.assertEqual(build_periods(MONTHLY, today=date(2026, 12, 31))[-1], date(2026, 12, 1))
        self.assertEqual(build_periods(MONTHLY, today=date(2027, 1, 1))[-1], date(2027, 1, 1))

    def test_quarterly_periods_start_in_january_april_july_october(self):
        periods = build_periods(QUARTERLY, today=date(2027, 2, 14))
        self.assertEqual(len(periods), 13)
        self.assertEqual(periods[0], date(2024, 1, 1))
        self.assertEqual(
            periods[-5:],
            [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1), date(2027, 1, 1)],
        )
        self.assertEqual(period_start_for(QUARTERLY, date(2026, 12, 31)), date(2026, 10, 1))
        self.assertEqual(period_start_for(QUARTERLY, date(2026, 3, 31)), date(2026, 1, 1))

    def test_annual_periods_start_on_the_first_of_january(self):
        periods = build_periods(ANNUAL, today=date(2026, 12, 31))
        self.assertEqual(periods[0], date(2014, 1, 1))
        self.assertEqual(periods[-1], date(2026, 1, 1))
        self.assertEqual(build_periods(ANNUAL, today=date(2027, 1, 1))[-1], date(2027, 1, 1))

    def test_shift_moves_forward_and_back_over_a_year_end(self):
        self.assertEqual(shift_period(MONTHLY, date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_period(MONTHLY, date(2027, 1, 1), -1), date(2026, 12, 1))
        self.assertEqual(shift_period(QUARTERLY, date(2026, 10, 1), 1), date(2027, 1, 1))
        self.assertEqual(shift_period(ANNUAL, date(2026, 1, 1), -2), date(2024, 1, 1))
        self.assertEqual(shift_period(WEEKLY, date(2026, 12, 28), 1), date(2027, 1, 4))

    def test_labels(self):
        self.assertEqual(period_label(WEEKLY, date(2026, 11, 2)), 'Week of Nov 02, 2026')
        self.assertEqual(period_label(MONTHLY, date(2026, 11, 1)), 'November 2026')
        self.assertEqual(period_label(QUARTERLY, date(2026, 10, 1)), 'Q4 2026')
        self.assertEqual(period_label(ANNUAL, date(2026, 1, 1)), '2026')
        self.assertEqual(period_column_label(WEEKLY, date(2026, 11, 2)), 'Nov 2')
        self.assertEqual(period_column_label(MONTHLY, date(2026, 11, 1)), 'Nov 2026')


class BoardBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Cadence Org')
        self.team = Team.objects.create(organization=self.org, name='Cadence Team')
        self.user = User.objects.create_user(
            username='cadenceuser', password='pw', first_name='Priya', last_name='Owner',
        )
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.ROLE_ADMIN)
        self.user.profile.teams.add(self.team)
        self.scorecard = Scorecard.objects.create(name='Harbour numbers', team=self.team)
        self.client.force_login(self.user)

    def metric(self, name, frequency=WEEKLY, **kwargs):
        return ScorecardMetric.objects.create(
            scorecard=self.scorecard, name=name, owner=self.user,
            metric_type=ScorecardMetric.TYPE_INTEGER, goal_value=Decimal('10'),
            goal_direction=ScorecardMetric.DIR_ABOVE, frequency=frequency, **kwargs,
        )

    def board(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        self.assertEqual(resp.status_code, 200)
        return resp

    def export_rows(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/export/')
        self.assertEqual(resp.status_code, 200)
        return list(csv.reader(io.StringIO(resp.content.decode())))


class WeeklyOnlyBoardTest(BoardBase):
    """A board with only weekly metrics keeps its single table."""

    def test_one_weekly_section_and_no_cadence_heading(self):
        self.metric('Berths occupied')
        resp = self.board()
        self.assertEqual([s['frequency'] for s in resp.context['sections']], [WEEKLY])
        self.assertTrue(resp.context['weekly_only'])
        self.assertEqual(resp.context['periods'], build_periods(WEEKLY))
        self.assertNotContains(resp, 'Weekly metrics')
        self.assertContains(resp, 'Enter this week')
        self.assertContains(resp, '<table', count=1)

    def test_column_headings_keep_the_month_and_day(self):
        self.metric('Berths occupied')
        monday = build_periods(WEEKLY)[0]
        self.assertContains(self.board(), f'>{monday.strftime("%b")} {monday.day}</a>')

    def test_export_is_one_table_with_weekly_dates(self):
        self.metric('Berths occupied')
        rows = self.export_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ['Metric', 'Owner', 'Goal'] + [p.isoformat() for p in build_periods(WEEKLY)])


class MixedBoardTest(BoardBase):
    """Weekly and monthly metrics each get a table with their own period columns."""

    def setUp(self):
        super().setUp()
        self.weekly = self.metric('Berths occupied')
        self.monthly = self.metric('Fuel sold', MONTHLY)
        self.weeks = build_periods(WEEKLY)
        self.months = build_periods(MONTHLY)

    def test_a_section_per_cadence_weekly_first(self):
        resp = self.board()
        sections = resp.context['sections']
        self.assertEqual([s['frequency'] for s in sections], [WEEKLY, MONTHLY])
        self.assertEqual(sections[0]['periods'], self.weeks)
        self.assertEqual(sections[1]['periods'], self.months)
        self.assertEqual([r['metric'] for r in sections[0]['table']], [self.weekly])
        self.assertEqual([r['metric'] for r in sections[1]['table']], [self.monthly])
        self.assertFalse(resp.context['weekly_only'])
        self.assertContains(resp, 'Weekly metrics')
        self.assertContains(resp, 'Monthly metrics')
        self.assertContains(resp, '<table', count=2)
        self.assertContains(resp, 'Enter current values')

    def test_monthly_columns_are_named_by_month(self):
        resp = self.board()
        for month in (self.months[0], self.months[-1]):
            self.assertContains(resp, f'>{month.strftime("%b %Y")}</a>')

    def test_each_table_marks_its_own_current_period(self):
        resp = self.board()
        self.assertContains(resp, 'NOW</div>', count=2)
        self.assertContains(resp, 'style="border-left:2px solid #0d6efd"', count=2)

    def test_monthly_entry_sits_in_its_month_column(self):
        entry = ScorecardEntry.objects.create(
            metric=self.monthly, period_start=self.months[4], value=Decimal('25'), entered_by=self.user,
        )
        row = self.board().context['sections'][1]['table'][0]
        self.assertEqual(row['period_cells'][4], (self.months[4], entry))
        self.assertEqual([c for c in row['cells'] if c], [entry])

    def test_value_stored_on_a_monday_before_this_change_shows_in_its_month(self):
        """Monthly metrics used to be saved against the Monday of the week they were entered in."""
        month = self.months[6]
        monday = period_start_for(WEEKLY, month + timedelta(days=17))
        self.assertNotEqual(monday, month)
        entry = ScorecardEntry.objects.create(
            metric=self.monthly, period_start=monday, value=Decimal('7'), entered_by=self.user,
        )
        row = self.board().context['sections'][1]['table'][0]
        self.assertEqual(row['cells'][6], entry)
        entry.refresh_from_db()
        self.assertEqual(entry.period_start, monday)

    def test_quarterly_and_annual_metrics_get_their_own_tables(self):
        self.metric('Customer survey', QUARTERLY)
        self.metric('Insurance premium', ANNUAL)
        resp = self.board()
        self.assertEqual(
            [s['frequency'] for s in resp.context['sections']], [WEEKLY, MONTHLY, QUARTERLY, ANNUAL],
        )
        quarter = build_periods(QUARTERLY)[-1]
        self.assertContains(resp, f'>Q{(quarter.month - 1) // 3 + 1} {quarter.year}</a>')
        self.assertContains(resp, f'>{date.today().year}</a>')

    def test_inactive_metric_does_not_make_a_section(self):
        self.monthly.is_active = False
        self.monthly.save()
        self.assertEqual([s['frequency'] for s in self.board().context['sections']], [WEEKLY])

    def test_export_has_a_table_per_cadence(self):
        ScorecardEntry.objects.create(
            metric=self.monthly, period_start=self.months[2], value=Decimal('1250'), entered_by=self.user,
        )
        rows = self.export_rows()
        self.assertEqual(rows[0], ['Metric', 'Owner', 'Goal'] + [p.isoformat() for p in self.weeks])
        self.assertEqual(rows[1][0], 'Berths occupied')
        self.assertEqual(rows[2], [])
        self.assertEqual(rows[3], ['Metric', 'Owner', 'Goal'] + [p.isoformat() for p in self.months])
        self.assertEqual(rows[4][:3], ['Fuel sold', 'Priya Owner', '≥ 10'])
        self.assertEqual(rows[4][3 + 2], '1,250')
        self.assertEqual([c for c in rows[4][3:] if c], ['1,250'])
        self.assertEqual(len(rows), 5)


class MonthlyOnlyBoardTest(BoardBase):
    def setUp(self):
        super().setUp()
        self.monthly = self.metric('Fuel sold', MONTHLY)
        self.months = build_periods(MONTHLY)

    def test_board_shows_only_the_monthly_table(self):
        resp = self.board()
        self.assertEqual([s['frequency'] for s in resp.context['sections']], [MONTHLY])
        self.assertContains(resp, 'Monthly metrics')
        self.assertContains(resp, '<table', count=1)

    def test_export_is_by_month(self):
        ScorecardEntry.objects.create(
            metric=self.monthly, period_start=self.months[-1], value=Decimal('12'), entered_by=self.user,
        )
        rows = self.export_rows()
        self.assertEqual(rows[0], ['Metric', 'Owner', 'Goal'] + [p.isoformat() for p in self.months])
        self.assertEqual(rows[1][-1], '12')
        self.assertEqual(len(rows), 2)

    def test_entry_form_saves_against_the_first_of_the_month(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/enter/')
        self.assertContains(resp, date.today().strftime('%B %Y'))
        resp = self.client.post(
            f'/scorecards/{self.scorecard.pk}/enter/', {f'value_{self.monthly.pk}': '14'}, follow=True,
        )
        entry = ScorecardEntry.objects.get(metric=self.monthly)
        self.assertEqual(entry.period_start, date.today().replace(day=1))
        self.assertTrue(entry.on_track)
        self.assertContains(resp, f'1 metric updated for {date.today().strftime("%B %Y")}.')

    def test_list_counts_the_monthly_metric_on_its_own_period(self):
        ScorecardEntry.objects.create(
            metric=self.monthly, period_start=self.months[-1], value=Decimal('12'), entered_by=self.user,
        )
        summary = self.client.get('/scorecards/').context['summaries'][0]
        self.assertEqual((summary['on_track'], summary['off_track'], summary['missing']), (1, 0, 0))


class MixedEntryFormTest(BoardBase):
    def test_each_metric_is_entered_for_its_own_current_period(self):
        weekly = self.metric('Berths occupied')
        monthly = self.metric('Fuel sold', MONTHLY)
        url = f'/scorecards/{self.scorecard.pk}/enter/'
        resp = self.client.get(url)
        self.assertContains(resp, 'Current period')
        self.assertContains(resp, period_label(WEEKLY, build_periods(WEEKLY)[-1]))
        self.assertContains(resp, period_label(MONTHLY, build_periods(MONTHLY)[-1]))

        resp = self.client.post(url, {f'value_{weekly.pk}': '11', f'value_{monthly.pk}': '9'}, follow=True)
        self.assertEqual(
            ScorecardEntry.objects.get(metric=weekly).period_start, build_periods(WEEKLY)[-1],
        )
        monthly_entry = ScorecardEntry.objects.get(metric=monthly)
        self.assertEqual(monthly_entry.period_start, build_periods(MONTHLY)[-1])
        self.assertFalse(monthly_entry.on_track)
        self.assertContains(resp, '2 metrics updated for the current period.')
