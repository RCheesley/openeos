import re
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Organization, Team
from apps.audit.models import AuditEvent
from apps.issues.models import Issue
from apps.meetings.models import Headline
from apps.rocks.models import Rock, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vto.models import SectionKey, VTO, VTOCoreValue, VTOSection

FIXTURE = Path(__file__).parent / 'fixtures' / 'strety_export'
CHART_FILE = 'accountability_chart - Organization Wide 2026.csv'


def utc(*parts):
    return datetime(*parts, tzinfo=dt_timezone.utc)


class StretyImportMixin:
    """An organisation with three members: Ada (admin), Ben and Dev. Cleo Vance is nobody."""

    def setUp(self):
        self.org = Organization.objects.create(name='Harbour Lights Ltd')
        self.ada = User.objects.create_user(
            username='ada', password='pw', first_name='Ada', last_name='Marsh'
        )
        self.ben = User.objects.create_user(
            username='bokoro', password='pw', first_name='Ben', last_name='Okoro'
        )
        self.dev = User.objects.create_user(
            username='dev.patel', password='pw', first_name='Dev', last_name='Patel'
        )
        self.priya = User.objects.create_user(username='priya', password='pw')
        Membership.objects.create(
            user=self.ada, organization=self.org, role=Membership.ROLE_ADMIN
        )
        for user in (self.ben, self.dev, self.priya):
            Membership.objects.create(user=user, organization=self.org)

    def run_import(self, *extra, folder=FIXTURE, org=None):
        out = StringIO()
        call_command(
            'import_strety', str(folder), '--organization', (org or self.org).slug, *extra,
            stdout=out,
        )
        return out.getvalue()

    @staticmethod
    def counts(output, model):
        """``(created, skipped, errors)`` for one model line of the printed summary."""
        pattern = rf'^\s+{re.escape(model)}\s+created\s+(\d+)\s+skipped\s+(\d+)\s+errors\s+(\d+)'
        match = re.search(pattern, output, re.MULTILINE)
        assert match, f'no summary line for {model!r} in:\n{output}'
        return tuple(int(n) for n in match.groups())

    def team(self, name):
        return Team.objects.get(organization=self.org, name=name)

    def copy_fixture(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        target = Path(tmp) / 'export'
        shutil.copytree(FIXTURE, target)
        return target


class TeamsAndRocksTest(StretyImportMixin, TestCase):
    def test_team_folders_become_teams(self):
        output = self.run_import()
        self.assertEqual(
            set(Team.objects.filter(organization=self.org).values_list('name', flat=True)),
            {'Leadership', 'Operations'},
        )
        self.assertEqual(self.counts(output, 'Teams'), (2, 0, 0))

    def test_goals_become_rocks(self):
        output = self.run_import()
        leadership = self.team('Leadership')
        launch = Rock.objects.get(team=leadership, title='Launch the harbour app')
        self.assertEqual(launch.owner, self.ada)
        self.assertEqual(launch.created_by, self.ben)
        self.assertTrue(launch.is_company_rock)
        self.assertEqual((launch.quarter, launch.year), (4, 2026))
        self.assertEqual(launch.due_date, date(2026, 12, 31))
        self.assertEqual(launch.status, Rock.STATUS_ON_TRACK)
        self.assertEqual(launch.created_at, utc(2026, 9, 20, 10, 0))

        hire = Rock.objects.get(team=leadership, title='Hire a second engineer')
        self.assertEqual(hire.status, Rock.STATUS_OFF_TRACK)
        self.assertEqual(hire.owner, self.ben)
        self.assertFalse(hire.is_company_rock)
        self.assertIn('Target Value: 2', hire.description)
        self.assertIn('Current Value: 1', hire.description)

        closed = Rock.objects.get(team=leadership, title='Close the Q3 books')
        self.assertEqual(closed.status, Rock.STATUS_COMPLETE)
        self.assertEqual((closed.quarter, closed.year), (3, 2026))

        slipway = Rock.objects.get(team=self.team('Operations'), title='Repaint the slipway')
        self.assertEqual(slipway.status, Rock.STATUS_OFF_TRACK)
        self.assertEqual(slipway.owner, self.dev, 'matched by first name alone')
        self.assertEqual(slipway.created_by, self.priya, 'matched by username')
        self.assertEqual(self.counts(output, 'Rocks'), (4, 1, 0))

    def test_archived_goals_are_skipped_unless_asked_for(self):
        self.run_import()
        self.assertFalse(Rock.objects.filter(title='Old archived rock').exists())
        self.assertFalse(RockMilestone.objects.filter(title='Should be skipped').exists())

        output = self.run_import('--include-archived')
        old = Rock.objects.get(title='Old archived rock')
        self.assertEqual(old.status, Rock.STATUS_OFF_TRACK)
        self.assertEqual(old.owner, self.ada, 'Cleo Vance is unknown, so the importer owns it')
        self.assertTrue(old.milestones.filter(title='Should be skipped').exists())
        self.assertEqual(self.counts(output, 'Rocks'), (1, 4, 0))

    def test_milestones_attach_to_their_rock(self):
        output = self.run_import()
        launch = Rock.objects.get(title='Launch the harbour app')
        milestones = list(launch.milestones.order_by('order'))
        self.assertEqual([m.title for m in milestones],
                         ['Design signed off', 'Beta with five crews'])
        self.assertTrue(milestones[0].is_complete)
        self.assertEqual(milestones[0].completed_at, utc(2026, 10, 20, 16, 0))
        self.assertEqual(milestones[0].due_date, date(2026, 10, 31))
        self.assertFalse(milestones[1].is_complete)
        self.assertIsNone(milestones[1].completed_at)
        self.assertEqual(Rock.objects.get(title='Hire a second engineer').milestones.count(), 1)
        self.assertEqual(self.counts(output, 'Rock milestones'), (3, 1, 1))
        self.assertIn('no goal titled "No such goal"', output)

    def test_bad_row_is_reported_and_the_rest_imported(self):
        folder = self.copy_fixture()
        goals = folder / 'Leadership' / 'goals.csv'
        with goals.open('a') as handle:
            handle.write('Broken rock,On track,No,Ada Marsh,Ada Marsh,,next week,,,,No,,\n')
        output = self.run_import(folder=folder)
        self.assertEqual(self.counts(output, 'Rocks'), (4, 1, 1))
        self.assertIn('Leadership/goals.csv line 6', output)
        self.assertIn('not a date', output)
        self.assertFalse(Rock.objects.filter(title='Broken rock').exists())


class IssuesAndToDosTest(StretyImportMixin, TestCase):
    def test_issues(self):
        output = self.run_import()
        leadership = self.team('Leadership')
        fees = Issue.objects.get(title='Berth fees rising')
        self.assertEqual(fees.originating_team, leadership)
        self.assertEqual(fees.issue_type, Issue.TYPE_SHORT_TERM)
        self.assertEqual(fees.status, Issue.STATUS_OPEN)
        self.assertEqual(fees.created_by, self.ada)
        self.assertEqual(fees.created_at, utc(2026, 9, 22, 11, 0))

        crane = Issue.objects.get(title='Replace the crane')
        self.assertEqual(crane.issue_type, Issue.TYPE_LONG_TERM)
        self.assertEqual(crane.created_by, self.ben)

        parking = Issue.objects.get(title='Winter mooring policy')
        self.assertEqual(parking.issue_type, Issue.TYPE_LONG_TERM, 'Parking lot → long term')
        self.assertEqual(parking.originating_team, leadership, 'blank Team → folder team')

        gate = Issue.objects.get(title='Broken gate lock')
        self.assertEqual(gate.originating_team, self.team('Operations'), 'Team column wins')
        self.assertEqual(gate.status, Issue.STATUS_RESOLVED)
        self.assertEqual(gate.created_by, self.dev)

        self.assertEqual(self.counts(output, 'Issues'), (4, 0, 0))
        self.assertIn('Issue priority and owner are not carried', output)

    def test_todos(self):
        output = self.run_import()
        leadership = self.team('Leadership')
        letter = ToDo.objects.get(title='Send the berth fee letter')
        self.assertEqual((letter.owner, letter.team), (self.ada, leadership))
        self.assertEqual(letter.status, ToDo.STATUS_OPEN)
        self.assertIsNone(letter.completed_at)
        self.assertEqual(letter.due_date, date(2026, 10, 28))
        self.assertEqual(letter.created_at, utc(2026, 10, 14, 9, 0))

        survey = ToDo.objects.get(title='Book the crane survey')
        self.assertEqual((survey.owner, survey.team), (self.ben, leadership))
        self.assertEqual(survey.status, ToDo.STATUS_COMPLETE)
        self.assertEqual(survey.completed_at, utc(2026, 10, 19, 15, 30))

        bylaws = ToDo.objects.get(title='Read the harbour bylaws')
        self.assertEqual(bylaws.owner, self.ada, 'unknown assignee → the importing user')
        self.assertEqual(bylaws.team, leadership, 'a personal to-do still needs a team')
        self.assertEqual(bylaws.due_date, date.today() + timedelta(days=7))

        pump = ToDo.objects.get(title='Service the fuel pump')
        self.assertEqual((pump.owner, pump.team), (self.dev, self.team('Operations')))
        self.assertEqual(self.counts(output, 'To-Dos'), (4, 0, 0))


class ScorecardsAndHeadlinesTest(StretyImportMixin, TestCase):
    def test_metrics_become_scorecard_metrics_with_latest_entries(self):
        output = self.run_import()
        scorecard = Scorecard.objects.get(team=self.team('Leadership'))
        self.assertEqual(scorecard.name, 'Leadership Scorecard')
        metrics = {m.name: m for m in scorecard.metrics.all()}
        self.assertEqual(
            list(scorecard.metrics.order_by('order').values_list('name', flat=True)),
            ['Weekly L10 held', 'Berths occupied', 'Cash in bank', 'Open complaints'],
        )

        l10 = metrics['Weekly L10 held']
        self.assertEqual(l10.metric_type, ScorecardMetric.TYPE_INTEGER)
        self.assertEqual(l10.goal_direction, ScorecardMetric.DIR_EQUAL)
        self.assertEqual(l10.goal_value, Decimal('1'))
        self.assertEqual(l10.frequency, ScorecardMetric.FREQ_WEEKLY)
        self.assertEqual(l10.owner, self.ada)
        entry = l10.entries.get()
        self.assertEqual(entry.period_start, date(2026, 10, 12), 'Monday of that week')
        self.assertEqual(entry.value, Decimal('1'))
        self.assertTrue(entry.on_track)
        self.assertEqual(entry.entered_by, self.ada)

        berths = metrics['Berths occupied']
        self.assertEqual(berths.metric_type, ScorecardMetric.TYPE_PERCENTAGE)
        self.assertEqual(berths.goal_direction, ScorecardMetric.DIR_ABOVE)
        self.assertEqual(berths.goal_value, Decimal('85'))
        self.assertEqual(berths.owner, self.ben)
        self.assertEqual(berths.entries.get().value, Decimal('88.5'))

        cash = metrics['Cash in bank']
        self.assertEqual(cash.metric_type, ScorecardMetric.TYPE_FLOAT)
        self.assertEqual(cash.goal_value, Decimal('50000'))
        self.assertEqual(cash.frequency, ScorecardMetric.FREQ_MONTHLY)
        cash_entry = cash.entries.get()
        self.assertEqual(cash_entry.period_start, date(2026, 10, 1), 'first of the month')
        self.assertEqual(cash_entry.value, Decimal('61200'))

        complaints = metrics['Open complaints']
        self.assertEqual(complaints.metric_type, ScorecardMetric.TYPE_INTEGER)
        self.assertEqual(complaints.goal_direction, ScorecardMetric.DIR_BELOW)
        self.assertEqual(complaints.frequency, ScorecardMetric.FREQ_MONTHLY, 'Quarterly → monthly')
        self.assertEqual(complaints.owner, self.dev)
        self.assertEqual(complaints.entries.count(), 0)
        self.assertIn('Check-in frequency "Quarterly" is not available', output)

        fuel = ScorecardMetric.objects.get(name='Fuel sold (litres)')
        self.assertEqual(fuel.scorecard.team, self.team('Operations'))
        self.assertEqual(self.counts(output, 'Scorecards'), (2, 0, 0))
        self.assertEqual(self.counts(output, 'Scorecard metrics'), (5, 0, 0))
        self.assertEqual(self.counts(output, 'Scorecard entries'), (4, 0, 0))
        self.assertEqual(ScorecardEntry.objects.count(), 4)

    def test_headlines_are_counted_and_skipped(self):
        output = self.run_import()
        self.assertEqual(Headline.objects.count(), 0)
        self.assertIn('Headlines skipped (2;', output)
        self.assertIn('Leadership: New pontoon arrived', output)
        self.assertIn('Leadership: Ferry schedule changing', output)


class VTOTest(StretyImportMixin, TestCase):
    def test_core_values_and_sections(self):
        output = self.run_import()
        vto = VTO.objects.get(organization=self.org)
        values = list(vto.core_values.order_by('order'))
        self.assertEqual([v.name for v in values], ['Seaworthy', 'Neighbourly', 'Plain speaking'])
        self.assertEqual(values[0].description, 'We fix it before it fails.')
        self.assertNotIn('id:', values[0].name)

        content = {s.key: s.content for s in vto.sections.all()}
        self.assertEqual(content[SectionKey.CORE_FOCUS_PURPOSE],
                         'Keeping small working harbours alive.')
        self.assertEqual(content[SectionKey.CORE_FOCUS_NICHE],
                         'Berthing, fuel and repairs for working boats under 15 metres.')
        self.assertEqual(
            content[SectionKey.TEN_YEAR_TARGET],
            'By 2036, every working harbour on the east coast uses a Harbour Lights berth.',
        )
        self.assertEqual(content[SectionKey.TARGET_MARKET],
                         'Owner-skippers of working boats on the east coast of England.')
        self.assertEqual(content[SectionKey.THREE_UNIQUES_1],
                         'Always open — A person on the quay 24 hours a day.')
        self.assertEqual(content[SectionKey.THREE_UNIQUES_2], 'Repairs quoted within the hour.')
        self.assertEqual(content[SectionKey.THREE_UNIQUES_3],
                         'Fair fuel — Fuel at cost plus a fixed margin, published monthly.')
        self.assertEqual(content[SectionKey.PROVEN_PROCESS],
                         'Arrive, berth, refuel, repair, return.')
        self.assertEqual(content[SectionKey.GUARANTEE],
                         'Berthed within the hour or the first night is free.')
        self.assertEqual(
            content[SectionKey.THREE_YEAR_PICTURE],
            'Target Date: 2029-09-30\nRevenue: £2,400,000\nProfit: £310,000\nBerths: 180\n'
            'Harbours: 3',
        )
        self.assertEqual(
            content[SectionKey.THREE_YEAR_GOALS],
            '- Second harbour open (open) — A second harbour running on the same rhythm.',
        )
        self.assertEqual(content[SectionKey.ONE_YEAR_REVENUE], '£1,100,000')
        self.assertEqual(content[SectionKey.ONE_YEAR_PROFIT], '£120,000')
        self.assertEqual(
            content[SectionKey.ONE_YEAR_GOALS],
            'Target Date: 2027-09-30\nBerths: 120\nFuel margin: 8%\n'
            '- Night cover hired (open) — Two night staff hired by 31 March 2027.\n'
            '- Fuel pricing published (done) — Monthly fuel price sheet on the noticeboard & '
            'website.',
        )
        for section in vto.sections.all():
            self.assertEqual(section.last_edited_by, self.ada)
        self.assertEqual(self.counts(output, 'VTO core values'), (3, 0, 0))
        self.assertEqual(self.counts(output, 'VTO sections'), (14, 0, 0))
        self.assertIn('4 uniques found in vto.md; only the first three', output)

    def test_existing_sections_and_values_are_kept(self):
        vto = VTO.for_org(self.org)
        VTOSection.objects.create(vto=vto, key=SectionKey.GUARANTEE, content='Keep me')
        VTOSection.objects.create(vto=vto, key=SectionKey.CORE_FOCUS_NICHE, content='')
        VTOCoreValue.objects.create(vto=vto, name='seaworthy', description='Already here')
        output = self.run_import()
        self.assertEqual(vto.get_content(SectionKey.GUARANTEE), 'Keep me')
        self.assertEqual(vto.get_content(SectionKey.CORE_FOCUS_NICHE),
                         'Berthing, fuel and repairs for working boats under 15 metres.')
        self.assertEqual(vto.core_values.count(), 3)
        self.assertEqual(self.counts(output, 'VTO core values'), (2, 1, 0))
        self.assertEqual(self.counts(output, 'VTO sections'), (13, 1, 0))

    def test_vto_and_chart_in_a_folder_named_after_the_organisation(self):
        folder = self.copy_fixture()
        org_dir = folder / 'Harbour Lights Ltd'
        org_dir.mkdir()
        (folder / 'vto.md').rename(org_dir / 'vto.md')
        (folder / CHART_FILE).rename(org_dir / CHART_FILE)
        (folder / 'Scratch').mkdir()
        output = self.run_import(folder=folder)
        self.assertEqual(VTO.objects.get(organization=self.org).core_values.count(), 3)
        self.assertEqual(AccountabilityNode.objects.filter(organization=self.org).count(), 6)
        self.assertFalse(Team.objects.filter(name='Harbour Lights Ltd').exists())
        self.assertFalse(Team.objects.filter(name='Scratch').exists())
        self.assertIn('Folder "Scratch" skipped', output)


class AccountabilityChartTest(StretyImportMixin, TestCase):
    def test_chart_rows_become_a_tree(self):
        output = self.run_import()
        nodes = {n.name: n for n in AccountabilityNode.objects.filter(organization=self.org)}
        self.assertEqual(len(nodes), 6)

        box = nodes["Owner's Box"]
        self.assertEqual(box.node_type, AccountabilityNode.TYPE_DEPARTMENT)
        self.assertIsNone(box.parent)
        self.assertIsNone(box.owner)

        visionary = nodes['Visionary']
        self.assertEqual(visionary.node_type, AccountabilityNode.TYPE_SEAT)
        self.assertIsNone(visionary.parent)
        self.assertEqual(visionary.owner, self.ada)
        self.assertEqual(
            list(visionary.roles.order_by('order').values_list('description', flat=True)),
            ['Vision', 'Culture', 'Big relationships'],
        )

        integrator = nodes['Integrator']
        self.assertEqual(integrator.parent, visionary)
        self.assertEqual(integrator.owner, self.ben)

        operations = nodes['Operations']
        self.assertEqual(operations.parent, integrator)
        self.assertEqual(operations.owner, self.dev, 'first seat holder owns the seat')
        self.assertEqual(
            list(operations.roles.order_by('order').values_list('description', flat=True)),
            ['Fuel', 'Repairs', 'Berthing'],
        )
        self.assertIn('Seat "Operations" has more than one holder', output)
        self.assertIn('Cleo Vance', output)

        finance = nodes['Finance']
        self.assertTrue(finance.is_vacant)
        self.assertEqual(finance.parent, integrator)

        harbourmaster = nodes['Harbourmaster']
        self.assertIsNone(harbourmaster.parent)
        self.assertIn('"Harbourmaster" reports to "Marina Manager", which is not', output)

        self.assertEqual(self.counts(output, 'Accountability seats'), (6, 0, 0))
        self.assertEqual(self.counts(output, 'Accountability roles'), (11, 0, 0))
        self.assertEqual(AccountabilityRole.objects.count(), 11)


class PeopleTest(StretyImportMixin, TestCase):
    def test_unmatched_names_are_listed_and_not_created(self):
        output = self.run_import()
        self.assertIn('Names not matched to a member', output)
        self.assertIn('  - Cleo Vance', output)
        self.assertFalse(User.objects.filter(first_name='Cleo').exists())
        self.assertEqual(User.objects.count(), 4)

    def test_create_users_adds_a_member_for_each_unmatched_name(self):
        output = self.run_import('--create-users')
        cleo = User.objects.get(username='cleo-vance')
        self.assertEqual((cleo.first_name, cleo.last_name), ('Cleo', 'Vance'))
        self.assertFalse(cleo.has_usable_password())
        self.assertTrue(hasattr(cleo, 'profile'))
        membership = Membership.objects.get(user=cleo, organization=self.org)
        self.assertEqual(membership.role, Membership.ROLE_MEMBER)
        self.assertEqual(ToDo.objects.get(title='Read the harbour bylaws').owner, cleo)
        self.assertEqual(User.objects.count(), 5, 'one new user, used everywhere she appears')
        self.assertIn('Users created', output)
        self.assertIn('Cleo Vance → cleo-vance', output)
        self.assertNotIn('Names not matched', output)

    def test_created_username_does_not_collide(self):
        User.objects.create_user(username='cleo-vance', password='pw')
        self.run_import('--create-users')
        self.assertTrue(User.objects.filter(username='cleo-vance-2', first_name='Cleo').exists())

    def test_ambiguous_first_name_is_not_matched(self):
        other_dev = User.objects.create_user(username='dev2', first_name='Dev', last_name='Two')
        Membership.objects.create(user=other_dev, organization=self.org)
        output = self.run_import()
        self.assertIn('  - Dev', output)
        self.assertEqual(Rock.objects.get(title='Repaint the slipway').owner, self.ada)

    def test_members_of_other_organisations_are_not_matched(self):
        other = Organization.objects.create(name='Elsewhere')
        cleo = User.objects.create_user(username='cleo', first_name='Cleo', last_name='Vance')
        Membership.objects.create(user=cleo, organization=other)
        output = self.run_import()
        self.assertIn('  - Cleo Vance', output)
        self.assertEqual(ToDo.objects.get(title='Read the harbour bylaws').owner, self.ada)

    def test_name_shared_with_a_superuser_member_goes_to_the_importing_user(self):
        # A platform operator who is also a member, with the same name as the person
        # running the import, must not win the match.
        ops = User.objects.create_superuser(
            username='ops', password='pw', first_name='Ada', last_name='Marsh'
        )
        Membership.objects.create(user=ops, organization=self.org, role=Membership.ROLE_ADMIN)
        self.run_import('--user', 'ada')
        self.assertEqual(Rock.objects.get(title='Launch the harbour app').owner, self.ada)

    def test_superuser_only_matches_when_nobody_else_does(self):
        ops = User.objects.create_superuser(
            username='ops', password='pw', first_name='Ada', last_name='Marsh'
        )
        Membership.objects.create(user=ops, organization=self.org, role=Membership.ROLE_ADMIN)
        self.run_import('--user', 'bokoro')
        self.assertEqual(Rock.objects.get(title='Launch the harbour app').owner, self.ada)

    def test_importing_user_joins_the_teams_the_import_creates(self):
        self.run_import('--user', 'bokoro')
        team_names = set(self.ben.profile.teams.values_list('name', flat=True))
        self.assertEqual(team_names, {'Leadership', 'Operations'})

    def test_explicit_importing_user(self):
        self.run_import('--user', 'bokoro')
        self.assertEqual(ToDo.objects.get(title='Read the harbour bylaws').owner, self.ben)
        self.assertEqual(
            VTOSection.objects.get(key=SectionKey.GUARANTEE).last_edited_by, self.ben
        )

    def test_no_importing_user_available_is_an_error(self):
        Membership.objects.filter(organization=self.org).update(role=Membership.ROLE_MEMBER)
        with self.assertRaisesMessage(CommandError, 'pass --user'):
            self.run_import()

    def test_unknown_user_is_an_error(self):
        with self.assertRaisesMessage(CommandError, 'No user with username "nobody"'):
            self.run_import('--user', 'nobody')


class RunModesTest(StretyImportMixin, TestCase):
    MODELS = (Team, Rock, RockMilestone, Issue, ToDo, Scorecard, ScorecardMetric,
              ScorecardEntry, VTO, VTOCoreValue, VTOSection, AccountabilityNode,
              AccountabilityRole, AuditEvent)

    def snapshot(self):
        return {model.__name__: model.objects.count() for model in self.MODELS}

    def test_dry_run_prints_the_summary_and_saves_nothing(self):
        before = self.snapshot()
        users_before = User.objects.count()
        output = self.run_import('--dry-run', '--create-users')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(User.objects.count(), users_before)
        self.assertIn('dry run, nothing was saved', output)
        self.assertIn('Dry run: nothing was saved.', output)
        self.assertEqual(self.counts(output, 'Rocks'), (4, 1, 0))
        self.assertEqual(self.counts(output, 'Teams'), (2, 0, 0))
        self.assertEqual(self.counts(output, 'Accountability seats'), (6, 0, 0))
        self.assertIn('Cleo Vance → cleo-vance', output)

    def test_second_run_skips_everything(self):
        first = self.run_import()
        after_first = self.snapshot()
        second = self.run_import()
        self.assertEqual(
            {k: v for k, v in self.snapshot().items() if k != 'AuditEvent'},
            {k: v for k, v in after_first.items() if k != 'AuditEvent'},
        )
        for model in ('Teams', 'Rocks', 'Rock milestones', 'Issues', 'To-Dos', 'Scorecards',
                      'Scorecard metrics', 'Scorecard entries', 'VTO core values',
                      'VTO sections', 'Accountability seats', 'Accountability roles'):
            created, skipped, _ = self.counts(second, model)
            self.assertEqual(created, 0, f'{model} were created again:\n{second}')
            if model not in ('Rock milestones', 'Scorecard entries', 'Accountability roles'):
                first_created, first_skipped, _ = self.counts(first, model)
                self.assertEqual(skipped, first_created + first_skipped, model)
        self.assertEqual(self.counts(second, 'Rock milestones'), (0, 4, 1))
        self.assertEqual(self.counts(second, 'Scorecard entries'), (0, 4, 0))

    def test_an_audit_event_is_recorded(self):
        self.run_import()
        event = AuditEvent.objects.get(action='organization.imported')
        self.assertEqual((event.actor, event.organization), (self.ada, self.org))
        self.assertEqual(event.details['source'], 'strety')
        self.assertFalse(event.details['dry_run'])

    def test_create_organization(self):
        out = StringIO()
        call_command(
            'import_strety', str(FIXTURE), '--create-organization', 'New Harbour',
            '--user', 'bokoro', stdout=out,
        )
        org = Organization.objects.get(name='New Harbour')
        self.assertEqual(org.slug, 'new-harbour')
        membership = Membership.objects.get(user=self.ben, organization=org)
        self.assertEqual(membership.role, Membership.ROLE_ADMIN)
        self.assertEqual(Team.objects.filter(organization=org).count(), 2)
        self.assertEqual(Team.objects.filter(organization=self.org).count(), 0)
        self.assertIn('Imported into "New Harbour"', out.getvalue())

    def test_create_organization_dry_run_leaves_no_organisation(self):
        out = StringIO()
        call_command(
            'import_strety', str(FIXTURE), '--create-organization', 'New Harbour',
            '--user', 'bokoro', '--dry-run', stdout=out,
        )
        self.assertFalse(Organization.objects.filter(name='New Harbour').exists())
        self.assertEqual(self.counts(out.getvalue(), 'Teams'), (2, 0, 0))

    def test_create_organization_that_exists_is_an_error(self):
        with self.assertRaisesMessage(CommandError, 'already exists'):
            call_command('import_strety', str(FIXTURE), '--create-organization',
                         'Harbour Lights Ltd', stdout=StringIO())

    def test_organization_and_create_organization_are_exclusive(self):
        with self.assertRaises(CommandError):
            call_command('import_strety', str(FIXTURE), '--organization', self.org.slug,
                         '--create-organization', 'X', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('import_strety', str(FIXTURE), stdout=StringIO())


class BadInputTest(StretyImportMixin, TestCase):
    def test_unknown_organisation(self):
        with self.assertRaisesMessage(CommandError, 'No organisation with slug "nope"'):
            call_command('import_strety', str(FIXTURE), '--organization', 'nope',
                         stdout=StringIO())

    def test_missing_folder(self):
        with self.assertRaisesMessage(CommandError, 'is not a folder'):
            self.run_import(folder=FIXTURE / 'does-not-exist')

    def test_folder_without_export_files(self):
        folder = self.copy_fixture() / 'Scratch'
        folder.mkdir()
        with self.assertRaisesMessage(CommandError, 'No Strety export files found'):
            self.run_import(folder=folder)

    def test_csv_missing_a_column_is_a_clean_error_and_imports_nothing(self):
        folder = self.copy_fixture()
        goals = folder / 'Leadership' / 'goals.csv'
        goals.write_text('Title,Status\nSomething,On track\n')
        with self.assertRaisesMessage(CommandError, 'goals.csv is missing column(s): Assignee'):
            self.run_import(folder=folder)
        self.assertEqual(Team.objects.filter(organization=self.org).count(), 0)
        self.assertEqual(VTOCoreValue.objects.count(), 0)
        self.assertEqual(AccountabilityNode.objects.count(), 0)

    def test_csv_row_with_too_many_values_is_a_clean_error(self):
        folder = self.copy_fixture()
        todos = folder / 'Operations' / 'todos.csv'
        with todos.open('a') as handle:
            handle.write('a,b,c,d,e,f,g,h,i,j,k,l,m,n\n')
        with self.assertRaisesMessage(CommandError, 'more values than the header'):
            self.run_import(folder=folder)
        self.assertEqual(ToDo.objects.count(), 0)

    def test_empty_csv_is_a_clean_error(self):
        folder = self.copy_fixture()
        (folder / 'Operations' / 'metrics.csv').write_text('')
        with self.assertRaisesMessage(CommandError, 'metrics.csv is empty'):
            self.run_import(folder=folder)

    def test_two_vto_files_is_a_clean_error(self):
        folder = self.copy_fixture()
        (folder / 'Other Org').mkdir()
        (folder / 'Other Org' / 'vto.md').write_text('# Other V/TO\n')
        with self.assertRaisesMessage(CommandError, 'more than one place'):
            self.run_import(folder=folder)
