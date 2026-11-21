"""The warning band: three-state judgement, validation and every place the state is shown."""
import csv
import io
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Membership, Organization, Team
from apps.accounts.tests.test_portability import MediaRootMixin, export_to_bytes, populate_org
from apps.meetings.models import Meeting
from apps.scorecards.forms import ScorecardMetricForm
from apps.scorecards.models import (
    STATUS_OFF_TRACK, STATUS_ON_TRACK, STATUS_WARNING,
    Scorecard, ScorecardEntry, ScorecardMetric, build_periods,
)

ABOVE = ScorecardMetric.DIR_ABOVE
BELOW = ScorecardMetric.DIR_BELOW
EQUAL = ScorecardMetric.DIR_EQUAL
MONTHLY = ScorecardMetric.FREQ_MONTHLY


def unsaved(direction, goal='10', warning=None):
    return ScorecardMetric(
        goal_value=Decimal(goal), goal_direction=direction,
        warning_value=None if warning is None else Decimal(warning),
    )


class ComputeStatusTest(SimpleTestCase):
    def assert_statuses(self, metric, expected):
        for value, status in expected.items():
            with self.subTest(value=value):
                self.assertEqual(metric.compute_status(Decimal(value)), status)

    def test_at_least_goal_with_a_warning_value(self):
        self.assert_statuses(unsaved(ABOVE, warning='8'), {
            '15': STATUS_ON_TRACK, '10': STATUS_ON_TRACK,
            '9.9999': STATUS_WARNING, '9': STATUS_WARNING, '8': STATUS_WARNING,
            '7.9999': STATUS_OFF_TRACK, '0': STATUS_OFF_TRACK,
        })

    def test_at_most_goal_with_a_warning_value(self):
        self.assert_statuses(unsaved(BELOW, warning='12'), {
            '3': STATUS_ON_TRACK, '10': STATUS_ON_TRACK,
            '10.0001': STATUS_WARNING, '11': STATUS_WARNING, '12': STATUS_WARNING,
            '12.0001': STATUS_OFF_TRACK, '40': STATUS_OFF_TRACK,
        })

    def test_equal_goal_has_the_band_on_both_sides(self):
        for warning in ('8', '12'):
            with self.subTest(warning=warning):
                self.assert_statuses(unsaved(EQUAL, warning=warning), {
                    '10': STATUS_ON_TRACK,
                    '8': STATUS_WARNING, '9': STATUS_WARNING, '11': STATUS_WARNING, '12': STATUS_WARNING,
                    '7.9999': STATUS_OFF_TRACK, '12.0001': STATUS_OFF_TRACK,
                })

    def test_without_a_warning_value_there_are_two_states(self):
        self.assert_statuses(unsaved(ABOVE), {'10': STATUS_ON_TRACK, '9.9': STATUS_OFF_TRACK})
        self.assert_statuses(unsaved(BELOW), {'10': STATUS_ON_TRACK, '10.1': STATUS_OFF_TRACK})
        self.assert_statuses(unsaved(EQUAL), {'10': STATUS_ON_TRACK, '9': STATUS_OFF_TRACK, '11': STATUS_OFF_TRACK})

    def test_warning_band_in_words(self):
        self.assertEqual(unsaved(ABOVE, warning='8').format_warning(), 'Warning from 8')
        self.assertEqual(unsaved(BELOW, warning='12').format_warning(), 'Warning up to 12')
        self.assertEqual(unsaved(EQUAL, warning='8').format_warning(), 'Warning within 2')
        self.assertEqual(unsaved(ABOVE).format_warning(), '')


class WarningValueValidationTest(SimpleTestCase):
    def assert_rejected(self, direction, warning):
        with self.assertRaises(ValidationError) as caught:
            unsaved(direction, warning=warning).clean()
        self.assertIn('warning_value', caught.exception.message_dict)

    def test_at_least_goal_needs_the_warning_below_the_goal(self):
        unsaved(ABOVE, warning='9.9').clean()
        self.assert_rejected(ABOVE, '10')
        self.assert_rejected(ABOVE, '11')

    def test_at_most_goal_needs_the_warning_above_the_goal(self):
        unsaved(BELOW, warning='10.1').clean()
        self.assert_rejected(BELOW, '10')
        self.assert_rejected(BELOW, '9')

    def test_equal_goal_needs_a_warning_that_differs(self):
        unsaved(EQUAL, warning='9').clean()
        unsaved(EQUAL, warning='11').clean()
        self.assert_rejected(EQUAL, '10')

    def test_no_warning_value_is_valid(self):
        for direction in (ABOVE, BELOW, EQUAL):
            unsaved(direction).clean()


class ThresholdBase(TestCase):
    """A board with one metric of each state this week, and one with no warning value."""

    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights')
        self.team = Team.objects.create(organization=self.org, name='Harbour Team')
        self.user = User.objects.create_user(username='priya', password='pw', first_name='Priya', last_name='Owner')
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.ROLE_ADMIN)
        self.user.profile.teams.add(self.team)
        self.scorecard = Scorecard.objects.create(name='Harbour numbers', team=self.team)
        self.weeks = build_periods(ScorecardMetric.FREQ_WEEKLY)
        self.green = self.metric('Berths occupied', warning='8')
        self.amber = self.metric('Visitor nights', warning='8')
        self.red = self.metric('Fuel sold', warning='8')
        self.plain = self.metric('Moorings checked')
        self.enter(self.green, '12')
        self.amber_entry = self.enter(self.amber, '9')
        self.red_entry = self.enter(self.red, '3')
        self.client.force_login(self.user)

    def metric(self, name, warning=None, direction=ABOVE, frequency=ScorecardMetric.FREQ_WEEKLY):
        return ScorecardMetric.objects.create(
            scorecard=self.scorecard, name=name, owner=self.user,
            metric_type=ScorecardMetric.TYPE_INTEGER, goal_value=Decimal('10'), goal_direction=direction,
            warning_value=None if warning is None else Decimal(warning), frequency=frequency,
        )

    def enter(self, metric, value, period=None):
        return ScorecardEntry.objects.create(
            metric=metric, period_start=period or self.weeks[-1], value=Decimal(value), entered_by=self.user,
        )


class EntryJudgementTest(ThresholdBase):
    def test_a_saved_entry_records_its_state(self):
        self.amber_entry.refresh_from_db()
        self.assertFalse(self.amber_entry.on_track)
        self.assertTrue(self.amber_entry.in_warning)
        self.assertEqual(self.amber_entry.status, STATUS_WARNING)
        self.assertEqual(self.amber_entry.status_label, 'Warning')
        self.assertEqual(self.amber_entry.cell_class, 'table-warning')
        # Amber needs dark text to be readable.
        self.assertEqual(self.amber_entry.badge_class, 'bg-warning text-dark')
        self.red_entry.refresh_from_db()
        self.assertEqual((self.red_entry.on_track, self.red_entry.in_warning), (False, False))
        self.assertTrue(self.red_entry.is_off_track)
        self.assertFalse(self.amber_entry.is_off_track)

    def test_each_state_has_its_own_label_icon_and_colour(self):
        entries = [ScorecardEntry.objects.get(metric=m) for m in (self.green, self.amber, self.red)]
        for attribute in ('status_label', 'status_icon', 'cell_class', 'badge_class'):
            self.assertEqual(len({getattr(e, attribute) for e in entries}), 3, attribute)

    def test_existing_entries_keep_their_judgement_when_a_warning_value_is_added(self):
        old_red = self.enter(self.plain, '9')
        old_green = self.enter(self.plain, '11', period=self.weeks[-2])
        self.assertEqual(old_red.status, STATUS_OFF_TRACK)
        self.plain.warning_value = Decimal('8')
        self.plain.save()
        old_red.refresh_from_db()
        old_green.refresh_from_db()
        self.assertEqual((old_red.on_track, old_red.in_warning), (False, False))
        self.assertEqual(old_red.status, STATUS_OFF_TRACK)
        self.assertEqual(old_green.status, STATUS_ON_TRACK)
        # A value entered from now on is judged with the band.
        self.assertEqual(self.enter(self.plain, '9', period=self.weeks[-3]).status, STATUS_WARNING)

    def test_rows_stored_before_the_field_existed_read_as_red_or_green(self):
        # What the migration leaves on old rows: in_warning false whatever the value.
        ScorecardEntry.objects.filter(pk=self.amber_entry.pk).update(on_track=False, in_warning=False)
        self.amber_entry.refresh_from_db()
        self.assertEqual(self.amber_entry.status, STATUS_OFF_TRACK)

    def test_entering_through_the_form_judges_with_the_band(self):
        self.client.post(
            f'/scorecards/{self.scorecard.pk}/enter/', {f'value_{self.plain.pk}': '9', f'value_{self.red.pk}': '8'},
        )
        self.assertEqual(ScorecardEntry.objects.get(metric=self.plain).status, STATUS_OFF_TRACK)
        self.assertEqual(ScorecardEntry.objects.get(metric=self.red).status, STATUS_WARNING)


class MetricFormTest(ThresholdBase):
    def data(self, **overrides):
        data = {
            'name': 'Launches', 'owner': self.user.pk, 'metric_type': 'integer', 'goal_value': '10',
            'goal_direction': ABOVE, 'warning_value': '8', 'frequency': 'weekly', 'order': '0', 'is_active': 'on',
        }
        data.update(overrides)
        return data

    def test_form_saves_a_warning_value(self):
        resp = self.client.post(f'/scorecards/{self.scorecard.pk}/metrics/add/', self.data())
        self.assertRedirects(resp, f'/scorecards/{self.scorecard.pk}/')
        self.assertEqual(ScorecardMetric.objects.get(name='Launches').warning_value, Decimal('8'))

    def test_warning_value_is_optional(self):
        self.client.post(f'/scorecards/{self.scorecard.pk}/metrics/add/', self.data(warning_value=''))
        self.assertIsNone(ScorecardMetric.objects.get(name='Launches').warning_value)

    def test_form_rejects_a_warning_value_on_the_wrong_side_and_says_why(self):
        resp = self.client.post(f'/scorecards/{self.scorecard.pk}/metrics/add/', self.data(warning_value='12'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ScorecardMetric.objects.filter(name='Launches').exists())
        self.assertContains(resp, 'the warning value must be below the goal')
        # The rejected number is still in the field.
        self.assertContains(resp, 'value="12"')

    def test_form_validates_against_the_direction_posted(self):
        form = ScorecardMetricForm(self.data(goal_direction=BELOW, warning_value='12'), organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        form = ScorecardMetricForm(self.data(goal_direction=BELOW, warning_value='8'), organization=self.org)
        self.assertIn('warning_value', form.errors)

    def test_edit_form_has_a_labelled_warning_field_with_the_stored_value(self):
        resp = self.client.get(f'/scorecards/metric/{self.amber.pk}/edit/')
        self.assertContains(resp, '<label for="id_warning_value"')
        self.assertContains(resp, 'name="warning_value" id="id_warning_value"')
        self.assertContains(resp, 'value="8.0000"')


class SurfacesTest(ThresholdBase):
    def test_board_shows_three_states_in_words_and_symbols(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        for css, icon, label in (
            ('table-success', 'bi-check-circle', 'On track'),
            ('table-warning', 'bi-exclamation-circle', 'Warning'),
            ('table-danger', 'bi-x-circle', 'Off track'),
        ):
            self.assertContains(resp, f'<td class="text-center small {css}"', count=1)
            self.assertContains(
                resp,
                f'<i class="bi {icon}" style="font-size:.7rem" aria-hidden="true"></i>'
                f'<span class="visually-hidden">{label}:</span>',
                count=1,
            )
            self.assertContains(resp, f'title="{label}. Entered by Priya Owner', count=1)
        self.assertContains(resp, 'Warning from 8', count=3)
        self.assertContains(resp, 'Warning: missed the goal, inside the warning value')

    def test_board_offers_escalation_for_off_track_only(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/')
        self.assertContains(resp, f'/scorecards/entry/{self.red_entry.pk}/escalate/')
        self.assertNotContains(resp, f'/scorecards/entry/{self.amber_entry.pk}/escalate/')

    def test_entry_form_shows_three_states(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/enter/')
        for badge, icon, label in (
            ('bg-success', 'bi-check-circle', 'On track'),
            ('bg-warning text-dark', 'bi-exclamation-circle', 'Warning'),
            ('bg-danger', 'bi-x-circle', 'Off track'),
        ):
            self.assertContains(resp, f'<span class="badge {badge}">', count=1)
            self.assertContains(resp, f'<i class="bi {icon} me-1" aria-hidden="true"></i>', count=1)
            self.assertContains(resp, f'<div class="small">{label}</div>', count=1)
        self.assertContains(resp, 'Warning from 8', count=3)

    def test_list_summary_counts_warnings_apart(self):
        resp = self.client.get('/scorecards/')
        summary = resp.context['summaries'][0]
        self.assertEqual(
            (summary['on_track'], summary['warning'], summary['off_track'], summary['missing']), (1, 1, 1, 1),
        )
        self.assertContains(resp, '<i class="bi bi-exclamation-circle me-1"></i>1 warning')
        self.assertContains(resp, '1 off track')
        self.assertContains(resp, 'progress-bar bg-warning" style="width:25%"')
        # Bootstrap's plain amber text is too pale on white.
        self.assertNotContains(resp, 'class="text-warning"')

    def test_list_summary_has_no_warning_line_without_warnings(self):
        self.amber_entry.delete()
        resp = self.client.get('/scorecards/')
        self.assertNotContains(resp, ' warning</span>')

    def test_dashboard_counts_warnings_apart_from_off_track(self):
        resp = self.client.get('/')
        self.assertEqual(resp.context['scorecard_total'], 3)
        self.assertEqual(resp.context['scorecard_warning'], 1)
        self.assertEqual(resp.context['scorecard_off_track'], 1)
        self.assertContains(resp, '<div class="fs-4 fw-bold text-warning-emphasis">1</div>')
        self.assertContains(resp, 'aria-hidden="true"></i>Warning</div>')

    def test_dashboard_has_no_warning_count_without_warnings(self):
        self.amber_entry.delete()
        resp = self.client.get('/')
        self.assertEqual(resp.context['scorecard_warning'], 0)
        self.assertNotContains(resp, 'text-warning-emphasis')

    def test_weekly_meeting_segment_shows_three_states(self):
        monthly = self.metric('Slipway hours', warning='12', direction=BELOW, frequency=MONTHLY)
        self.enter(monthly, '11', period=build_periods(MONTHLY)[-1])
        meeting = Meeting.objects.create(team=self.team, scheduled_date=date.today(), created_by=self.user)
        meeting.start()
        meeting.current_segment = 1
        meeting.save(update_fields=['current_segment'])
        resp = self.client.get(f'/meetings/{meeting.pk}/')
        self.assertEqual(resp.context['segment_template'], 'meetings/segments/scorecard.html')
        self.assertContains(resp, 'aria-hidden="true"></i>On track: 12', count=1)
        self.assertContains(resp, 'aria-hidden="true"></i>Warning: 9', count=1)
        self.assertContains(resp, 'aria-hidden="true"></i>Off track: 3', count=1)
        # A monthly metric is shown with this month's value.
        self.assertContains(resp, 'aria-hidden="true"></i>Warning: 11', count=1)
        self.assertContains(resp, '<span class="badge bg-warning text-dark">', count=2)
        self.assertContains(resp, 'Not entered', count=1)
        self.assertContains(resp, 'warning from 8)', count=3)
        self.assertContains(resp, 'warning up to 12)', count=1)

    def test_csv_has_the_warning_value_and_a_status_per_period(self):
        resp = self.client.get(f'/scorecards/{self.scorecard.pk}/export/')
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        header = rows[0]
        # The columns that were there before keep their places; the new ones follow.
        self.assertEqual(header[:3], ['Metric', 'Owner', 'Goal'])
        self.assertEqual(header[3:16], [p.isoformat() for p in self.weeks])
        self.assertEqual(header[16], 'Warning')
        this_week = self.weeks[-1].isoformat()
        value_at, status_at = header.index(this_week), header.index(f'{this_week} status')
        self.assertEqual(len(header), 3 + 13 + 1 + 13)
        by_name = {row[0]: row for row in rows[1:]}
        self.assertEqual(
            {name: (row[16], row[value_at], row[status_at]) for name, row in by_name.items()},
            {
                'Berths occupied': ('Warning from 8', '12', 'On track'),
                'Visitor nights': ('Warning from 8', '9', 'Warning'),
                'Fuel sold': ('Warning from 8', '3', 'Off track'),
                'Moorings checked': ('', '', ''),
            },
        )
        # A period with no value has no status either.
        earlier = header.index(f'{self.weeks[0].isoformat()} status')
        self.assertEqual(by_name['Visitor nights'][earlier], '')


class PortabilityTest(MediaRootMixin, TestCase):
    def test_export_and_import_keep_the_warning_value_and_the_judgement(self):
        source = populate_org('Trend')
        metric = Scorecard.objects.get(team__organization=source['org']).metrics.get()
        metric.warning_value = Decimal('12.5')
        metric.save()
        # The goal is "at or below 10.5": 11 is a warning, 20 is off track, 7.25 was entered before.
        ScorecardEntry.objects.create(metric=metric, period_start=date(2026, 1, 12), value=Decimal('11'))
        ScorecardEntry.objects.create(metric=metric, period_start=date(2026, 1, 19), value=Decimal('20'))

        out = tempfile.mkdtemp(prefix='openeos-trend-')
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        archive = Path(out, 'trend.zip')
        blob, _ = export_to_bytes(source['org'], exported_by=source['admin'])
        archive.write_bytes(blob)
        call_command('import_organization', str(archive), '--slug', 'trend-copy', stdout=StringIO())

        copy = Organization.objects.get(slug='trend-copy')
        imported = Scorecard.objects.get(team__organization=copy).metrics.get()
        self.assertNotEqual(imported.pk, metric.pk)
        self.assertEqual(imported.warning_value, Decimal('12.5000'))
        self.assertEqual(
            [(e.value, e.on_track, e.in_warning, e.status) for e in imported.entries.order_by('period_start')],
            [
                (Decimal('7.2500'), True, False, STATUS_ON_TRACK),
                (Decimal('11.0000'), False, True, STATUS_WARNING),
                (Decimal('20.0000'), False, False, STATUS_OFF_TRACK),
            ],
        )
