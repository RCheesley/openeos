from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from apps.accounts.models import Organization, Team
from apps.scorecards.models import Scorecard, ScorecardMetric, ScorecardEntry, _current_week_start


def make_metric(goal_value='10', goal_direction=ScorecardMetric.DIR_ABOVE, name='Revenue'):
    org = Organization.objects.get_or_create(name='SC Org')[0]
    team = Team.objects.get_or_create(organization=org, name='SC Team')[0]
    sc = Scorecard.objects.get_or_create(name='Main', team=team)[0]
    user = User.objects.get_or_create(username='scuser')[0]
    return ScorecardMetric.objects.create(
        scorecard=sc, name=name, owner=user,
        goal_value=Decimal(goal_value),
        goal_direction=goal_direction,
    )


class ComputeOnTrackTest(TestCase):
    def test_above_on_track(self):
        m = make_metric(goal_value='10', goal_direction=ScorecardMetric.DIR_ABOVE)
        self.assertTrue(m.compute_on_track(Decimal('10')))
        self.assertTrue(m.compute_on_track(Decimal('15')))
        self.assertFalse(m.compute_on_track(Decimal('9')))

    def test_below_on_track(self):
        m = make_metric(goal_value='5', goal_direction=ScorecardMetric.DIR_BELOW, name='Tickets')
        self.assertTrue(m.compute_on_track(Decimal('5')))
        self.assertTrue(m.compute_on_track(Decimal('3')))
        self.assertFalse(m.compute_on_track(Decimal('6')))

    def test_equal_on_track(self):
        m = make_metric(goal_value='100', goal_direction=ScorecardMetric.DIR_EQUAL, name='Target')
        self.assertTrue(m.compute_on_track(Decimal('100')))
        self.assertFalse(m.compute_on_track(Decimal('99')))
        self.assertFalse(m.compute_on_track(Decimal('101')))


class ScorecardEntryTest(TestCase):
    def setUp(self):
        self.metric = make_metric(goal_value='10', goal_direction=ScorecardMetric.DIR_ABOVE)
        self.user = User.objects.get(username='scuser')

    def test_entry_sets_on_track_on_save(self):
        entry = ScorecardEntry.objects.create(
            metric=self.metric,
            value=Decimal('12'),
            period_start=_current_week_start(),
            entered_by=self.user,
        )
        self.assertTrue(entry.on_track)
        self.assertEqual(entry.cell_class, 'table-success')

    def test_entry_sets_off_track_on_save(self):
        entry = ScorecardEntry.objects.create(
            metric=self.metric,
            value=Decimal('5'),
            period_start=_current_week_start(),
            entered_by=self.user,
        )
        self.assertFalse(entry.on_track)
        self.assertEqual(entry.cell_class, 'table-danger')

    def test_scorecard_active_metrics(self):
        sc = self.metric.scorecard
        self.assertEqual(sc.active_metrics.count(), 1)

    def test_scorecard_metric_count(self):
        sc = self.metric.scorecard
        self.assertEqual(sc.metric_count, 1)

    def test_current_week_start_is_monday(self):
        ws = _current_week_start()
        self.assertEqual(ws.weekday(), 0)  # 0 = Monday
