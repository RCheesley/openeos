"""The sparkline beside each metric: geometry, gaps, cadences and the sentence that describes it."""
import re
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric, build_periods
from apps.scorecards.trends import (
    FALLING, HEIGHT, PAD, RISING, STEADY, WIDTH, build_trend, trend_direction, trend_text,
)

WEEKLY = ScorecardMetric.FREQ_WEEKLY
MONTHLY = ScorecardMetric.FREQ_MONTHLY
QUARTERLY = ScorecardMetric.FREQ_QUARTERLY
ANNUAL = ScorecardMetric.FREQ_ANNUAL
TODAY = date(2026, 11, 20)


class Cell:
    """Stands in for an entry: the chart only reads its value."""

    def __init__(self, value):
        self.value = Decimal(str(value))


def metric(frequency=WEEKLY, direction=ScorecardMetric.DIR_ABOVE, goal='10', warning=None, **extra):
    return ScorecardMetric(
        frequency=frequency, goal_direction=direction, goal_value=Decimal(goal),
        warning_value=None if warning is None else Decimal(warning), **extra,
    )


def cells(values):
    return [None if v is None else Cell(v) for v in values]


def trend_for(values, **metric_kwargs):
    m = metric(**metric_kwargs)
    return build_trend(m, build_periods(m.frequency, len(values), today=TODAY), cells(values))


def render(trend):
    return render_to_string('scorecards/_sparkline.html', {'trend': trend})


class DirectionTest(SimpleTestCase):
    def test_rising_falling_and_steady(self):
        self.assertEqual(trend_direction([1, 2, 3, 4]), RISING)
        self.assertEqual(trend_direction([40, 30, 20, 5]), FALLING)
        self.assertEqual(trend_direction([100, 101, 100, 101]), STEADY)
        self.assertEqual(trend_direction([7, 7, 7]), STEADY)
        self.assertEqual(trend_direction([0, 0]), STEADY)

    def test_gaps_are_skipped_not_read_as_zero(self):
        # Read as zeros, the gaps would make this series fall and then leap.
        self.assertEqual(trend_direction([10, None, None, 11, None, 12]), RISING)
        self.assertEqual(trend_direction([None, 12, None, 12, None]), STEADY)

    def test_fewer_than_two_values_have_no_direction(self):
        self.assertIsNone(trend_direction([None, None]))
        self.assertIsNone(trend_direction([None, 5, None]))
        self.assertIsNone(trend_direction([]))

    def test_a_noisy_series_is_judged_on_the_fitted_line_not_the_end_points(self):
        # The last value is below the first, yet the run of values climbs.
        self.assertEqual(trend_direction([5, 3, 6, 8, 7, 11, 12, 4]), RISING)
        # The last value is above the first, yet the run of values drops.
        self.assertEqual(trend_direction([4, 12, 11, 9, 8, 6, 3, 5]), FALLING)


class TrendTextTest(SimpleTestCase):
    def text(self, values, **metric_kwargs):
        return trend_for(values, **metric_kwargs)['text']

    def test_states_direction_latest_value_and_goal(self):
        values = [8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14]
        self.assertEqual(self.text(values), 'Rising over the last 13 weeks, latest 14 against a goal of at least 10.')

    def test_each_goal_direction_has_its_own_words(self):
        self.assertEqual(
            self.text([30, 20, 10], direction=ScorecardMetric.DIR_BELOW),
            'Falling over the last 3 weeks, latest 10 against a goal of at most 10.',
        )
        self.assertEqual(
            self.text([10, 10, 10], direction=ScorecardMetric.DIR_EQUAL),
            'Steady over the last 3 weeks, latest 10 against a goal of exactly 10.',
        )

    def test_names_the_warning_band_when_there_is_one(self):
        self.assertEqual(
            self.text([8, 9, 12], warning='8'),
            'Rising over the last 3 weeks, latest 12 against a goal of at least 10 (warning from 8).',
        )

    def test_each_cadence_names_its_own_periods(self):
        values = [1] * 12 + [5]
        for frequency, noun in ((WEEKLY, 'weeks'), (MONTHLY, 'months'), (QUARTERLY, 'quarters'), (ANNUAL, 'years')):
            with self.subTest(frequency=frequency):
                self.assertEqual(
                    self.text(values, frequency=frequency),
                    f'Rising over the last 13 {noun}, latest 5 against a goal of at least 10.',
                )

    def test_latest_value_from_an_earlier_period_names_that_period(self):
        self.assertEqual(
            self.text([4, 6, None], frequency=MONTHLY),
            'Rising over the last 3 months, latest 6 (Oct 2026) against a goal of at least 10.',
        )
        self.assertEqual(
            self.text([4, 6, None], frequency=QUARTERLY),
            'Rising over the last 3 quarters, latest 6 (Q3 2026) against a goal of at least 10.',
        )

    def test_one_value_and_no_values(self):
        self.assertEqual(
            self.text([None, None, 7]), 'One value entered in the last 3 weeks: 7 against a goal of at least 10.',
        )
        self.assertEqual(
            self.text([None, None, None]), 'No values entered in the last 3 weeks, against a goal of at least 10.',
        )

    def test_values_are_formatted_as_the_metric_formats_them(self):
        self.assertEqual(
            self.text([90, 95.5], metric_type=ScorecardMetric.TYPE_PERCENTAGE, goal='92'),
            'Rising over the last 2 weeks, latest 95.5% against a goal of at least 92.0%.',
        )

    def test_trend_text_can_be_called_directly(self):
        m = metric(frequency=ANNUAL)
        periods = build_periods(ANNUAL, 2, today=TODAY)
        self.assertEqual(
            trend_text(m, periods, [Decimal('20'), Decimal('10')]),
            'Falling over the last 2 years, latest 10 against a goal of at least 10.',
        )


class GeometryTest(SimpleTestCase):
    def test_full_series_is_one_line_across_the_width(self):
        trend = trend_for([8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14])
        self.assertEqual(len(trend['lines']), 1)
        self.assertEqual(trend['dots'], [])
        points = [tuple(map(float, p.split(','))) for p in trend['lines'][0].split()]
        self.assertEqual(len(points), 13)
        self.assertEqual(points[0], (PAD, HEIGHT - PAD))      # lowest value, bottom left
        self.assertEqual(points[-1], (WIDTH - PAD, PAD))      # highest value, top right
        self.assertEqual(trend['latest'], {'x': str(WIDTH - PAD), 'y': str(PAD)})
        for x, y in points:
            self.assertTrue(PAD <= x <= WIDTH - PAD and PAD <= y <= HEIGHT - PAD)

    def test_goal_line_sits_at_the_goal(self):
        # Values 0 to 20 with a goal of 10: the goal is half way up.
        trend = trend_for([0, 20])
        self.assertEqual(float(trend['goal_y']), HEIGHT / 2)
        self.assertEqual(trend['warning_ys'], [])

    def test_goal_outside_the_values_is_still_inside_the_chart(self):
        trend = trend_for([100, 120, 110])
        self.assertEqual(float(trend['goal_y']), HEIGHT - PAD)
        trend = trend_for([1, 2, 3], goal='50')
        self.assertEqual(float(trend['goal_y']), PAD)

    def test_warning_line_sits_at_the_warning_value(self):
        trend = trend_for([0, 20], warning='5')
        self.assertEqual(len(trend['warning_ys']), 1)
        self.assertEqual(float(trend['warning_ys'][0]), HEIGHT - PAD - (HEIGHT - 2 * PAD) / 4)

    def test_equal_goal_has_a_warning_line_each_side(self):
        trend = trend_for([0, 20], direction=ScorecardMetric.DIR_EQUAL, warning='5')
        self.assertEqual(
            [float(y) for y in trend['warning_ys']],
            [HEIGHT - PAD - (HEIGHT - 2 * PAD) / 4, PAD + (HEIGHT - 2 * PAD) / 4],
        )

    def test_missing_periods_break_the_line(self):
        trend = trend_for([5, 6, None, None, 8, 9, 10, None, 4, None, None, 7, 8])
        self.assertEqual([len(line.split()) for line in trend['lines']], [2, 3, 2])
        self.assertEqual(len(trend['dots']), 1)   # the lone 4
        # Nothing is drawn at zero: the lowest point is the 4, at the bottom edge.
        ys = [float(p.split(',')[1]) for line in trend['lines'] for p in line.split()]
        self.assertEqual(max(ys + [float(trend['dots'][0]['y'])]), HEIGHT - PAD)
        self.assertEqual(float(trend['dots'][0]['y']), HEIGHT - PAD)
        # The periods keep their places: the last value is at the right edge.
        self.assertEqual(float(trend['latest']['x']), WIDTH - PAD)

    def test_latest_marker_is_on_the_last_entered_value_not_the_last_period(self):
        trend = trend_for([5, 6, None, None, None])
        self.assertEqual(float(trend['latest']['x']), PAD + (WIDTH - 2 * PAD) / 4)

    def test_single_value_is_a_dot(self):
        trend = trend_for([None, None, 7, None])
        self.assertEqual(trend['lines'], [])
        self.assertEqual(len(trend['dots']), 1)
        self.assertIsNone(trend['direction'])

    def test_empty_series_still_has_the_goal_line(self):
        trend = trend_for([None] * 13)
        self.assertEqual((trend['lines'], trend['dots'], trend['latest']), ([], [], None))
        self.assertEqual(float(trend['goal_y']), HEIGHT / 2)

    def test_flat_series_on_the_goal_is_drawn_through_the_middle(self):
        trend = trend_for([10, 10, 10])
        self.assertEqual({p.split(',')[1] for p in trend['lines'][0].split()}, {str(HEIGHT // 2)})

    def test_every_cadence_draws_its_thirteen_periods(self):
        for frequency in (WEEKLY, MONTHLY, QUARTERLY, ANNUAL):
            with self.subTest(frequency=frequency):
                trend = trend_for(list(range(13)), frequency=frequency)
                self.assertEqual(len(trend['lines'][0].split()), 13)
                self.assertEqual(trend['direction'], RISING)

    def test_large_and_negative_numbers_stay_inside_the_chart(self):
        trend = trend_for([-5000000, 0, 12500000.5], goal='1000000')
        for point in trend['lines'][0].split():
            x, y = map(float, point.split(','))
            self.assertTrue(0 <= x <= WIDTH and 0 <= y <= HEIGHT)


class SvgMarkupTest(SimpleTestCase):
    def test_svg_carries_the_text_alternative_and_no_script_or_outside_asset(self):
        trend = trend_for([8, 9, None, 12], warning='8')
        svg = render(trend)
        self.assertIn('role="img"', svg)
        self.assertIn(f'aria-label="{trend["text"]}"', svg)
        self.assertIn(f'<title>{trend["text"]}</title>', svg)
        self.assertEqual(svg.count('<polyline'), 1)
        self.assertEqual(svg.count('class="metric-trend-goal"'), 1)
        self.assertEqual(svg.count('class="metric-trend-warning"'), 1)
        self.assertEqual(svg.count('class="metric-trend-dot"'), 1)
        self.assertEqual(svg.count('class="metric-trend-latest"'), 1)
        self.assertNotIn('<script', svg)
        self.assertNotIn('href', svg)
        # The only address is the SVG namespace, which nothing fetches.
        self.assertEqual(re.findall(r'https?://[^"]+', svg), ['http://www.w3.org/2000/svg'])

    def test_goal_and_warning_lines_differ_in_pattern_not_only_colour(self):
        svg = render(trend_for([8, 9], warning='8'))
        self.assertIn('stroke-dasharray="4 2"', svg)
        self.assertIn('stroke-dasharray="1 2"', svg)

    def test_empty_series_renders_only_the_goal_line(self):
        svg = render(trend_for([None, None, None]))
        self.assertEqual(svg.count('class="metric-trend-goal"'), 1)
        for absent in ('<polyline', '<circle', 'metric-trend-warning'):
            self.assertNotIn(absent, svg)
        self.assertIn('aria-label="No values entered in the last 3 weeks, against a goal of at least 10."', svg)

    def test_text_is_escaped(self):
        trend = trend_for([1, 2])
        trend['text'] = 'a "quoted" <b>'
        svg = render(trend)
        self.assertIn('aria-label="a &quot;quoted&quot; &lt;b&gt;"', svg)


class BoardTrendTest(TestCase):
    def setUp(self):
        org = Organization.objects.create(name='Harbour Lights')
        team = Team.objects.create(organization=org, name='Harbour Team')
        self.user = User.objects.create_user(username='priya', password='pw')
        Membership.objects.create(user=self.user, organization=org, role=Membership.ROLE_ADMIN)
        self.user.profile.teams.add(team)
        self.scorecard = Scorecard.objects.create(name='Harbour numbers', team=team)
        self.client.force_login(self.user)

    def metric(self, name, frequency, **extra):
        return ScorecardMetric.objects.create(
            scorecard=self.scorecard, name=name, owner=self.user, goal_value=Decimal('10'),
            frequency=frequency, **extra,
        )

    def test_board_draws_a_trend_for_every_metric_of_every_cadence(self):
        nouns = {WEEKLY: 'weeks', MONTHLY: 'months', QUARTERLY: 'quarters', ANNUAL: 'years'}
        for frequency in nouns:
            m = self.metric(f'{frequency} metric', frequency)
            periods = build_periods(frequency)
            ScorecardEntry.objects.create(metric=m, period_start=periods[-3], value=Decimal('6'))
            ScorecardEntry.objects.create(metric=m, period_start=periods[-1], value=Decimal('14'))
        self.metric('Nothing yet', WEEKLY, warning_value=Decimal('8'))
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        self.assertContains(resp, '<svg class="metric-trend" role="img"', count=5)
        self.assertContains(resp, '>Trend</th>', count=4)
        for noun in nouns.values():
            self.assertContains(
                resp, f'aria-label="Rising over the last 13 {noun}, latest 14 against a goal of at least 10."',
            )
        self.assertContains(
            resp,
            'aria-label="No values entered in the last 13 weeks, against a goal of at least 10 (warning from 8)."',
        )
        # The two values are a gap apart, so they are two dots, not a line through a zero.
        self.assertContains(resp, 'class="metric-trend-dot"', count=8)
        self.assertNotContains(resp, '<polyline')
        self.assertContains(resp, 'class="metric-trend-warning"', count=1)

    def test_a_value_stored_on_a_monday_inside_a_month_is_drawn_in_that_month(self):
        m = self.metric('Fuel sold', MONTHLY)
        months = build_periods(MONTHLY)
        ScorecardEntry.objects.create(metric=m, period_start=months[-2].replace(day=9), value=Decimal('5'))
        ScorecardEntry.objects.create(metric=m, period_start=months[-1], value=Decimal('15'))
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        trend = resp.context['sections'][0]['table'][0]['trend']
        self.assertEqual(len(trend['lines'][0].split()), 2)
        self.assertEqual(trend['direction'], RISING)
