"""Load a Strety export into one organisation.

Everything runs inside a single transaction. A dry run does the full import and
then rolls it back, so the summary it prints is the one a real run would print.
Re-running is safe: a row whose title already exists for its team (or for the
organisation, for the vision document and the chart) is counted as skipped.
"""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import UserProfile, Team
from apps.audit.services import record as record_audit_event
from apps.issues.models import Issue
from apps.rocks.models import Rock, RockMilestone
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.todos.models import ToDo
from apps.vto.models import SectionKey, VTO, VTOCoreValue, VTOSection

from .parsing import (
    REQUIRED_COLUMNS, StretyFormatError, is_blank_person, locate_export, normalise,
    parse_bool, parse_date, parse_datetime, parse_decimal, parse_goal_bullet,
    parse_vto_markdown, read_csv, split_list, strip_markdown,
)
from .people import PeopleResolver

MODELS = [
    'Teams', 'Rocks', 'Rock milestones', 'Issues', 'To-Dos', 'Scorecards',
    'Scorecard metrics', 'Scorecard entries', 'VTO core values', 'VTO sections',
    'Accountability seats', 'Accountability roles',
]

ROCK_STATUSES = {
    'on track': Rock.STATUS_ON_TRACK,
    'off track': Rock.STATUS_OFF_TRACK,
    'at risk': Rock.STATUS_OFF_TRACK,
    'behind': Rock.STATUS_OFF_TRACK,
    'completed': Rock.STATUS_COMPLETE,
    'complete': Rock.STATUS_COMPLETE,
    'done': Rock.STATUS_COMPLETE,
    'dropped': Rock.STATUS_DROPPED,
    'cancelled': Rock.STATUS_DROPPED,
    'canceled': Rock.STATUS_DROPPED,
}

ISSUE_TYPES = {
    'short term': Issue.TYPE_SHORT_TERM,
    'long term': Issue.TYPE_LONG_TERM,
    'parking lot': Issue.TYPE_LONG_TERM,
}

METRIC_TYPES = {
    'yes no': ScorecardMetric.TYPE_INTEGER,
    'boolean': ScorecardMetric.TYPE_INTEGER,
    'number': ScorecardMetric.TYPE_INTEGER,
    'integer': ScorecardMetric.TYPE_INTEGER,
    'count': ScorecardMetric.TYPE_INTEGER,
    'currency': ScorecardMetric.TYPE_FLOAT,
    'decimal': ScorecardMetric.TYPE_FLOAT,
    'float': ScorecardMetric.TYPE_FLOAT,
    'percentage': ScorecardMetric.TYPE_PERCENTAGE,
    'percent': ScorecardMetric.TYPE_PERCENTAGE,
}

GOAL_DIRECTIONS = {
    'gte': ScorecardMetric.DIR_ABOVE,
    'gt': ScorecardMetric.DIR_ABOVE,
    'above': ScorecardMetric.DIR_ABOVE,
    'lte': ScorecardMetric.DIR_BELOW,
    'lt': ScorecardMetric.DIR_BELOW,
    'below': ScorecardMetric.DIR_BELOW,
    'eq': ScorecardMetric.DIR_EQUAL,
    'equal': ScorecardMetric.DIR_EQUAL,
}

FREQUENCIES = {
    'weekly': ScorecardMetric.FREQ_WEEKLY,
    'monthly': ScorecardMetric.FREQ_MONTHLY,
}

ROW_ERRORS = (ValueError, ArithmeticError, KeyError)


class _DryRunRollback(Exception):
    """Raised at the end of a dry run so the transaction is rolled back."""


class ImportSummary:
    """Counts per model plus everything a person should know after the run."""

    def __init__(self):
        self.counts = OrderedDict((name, {'created': 0, 'skipped': 0, 'errors': 0})
                                  for name in MODELS)
        self.errors = []
        self.notes = []
        self.headlines = []
        self.unmatched_names = []
        self.created_users = []
        self.dry_run = False

    def created(self, model, count=1):
        self.counts[model]['created'] += count

    def skipped(self, model, count=1):
        self.counts[model]['skipped'] += count

    def error(self, model, message):
        self.counts[model]['errors'] += 1
        self.errors.append(message)

    def note(self, message):
        if message not in self.notes:
            self.notes.append(message)

    def total_created(self):
        return sum(row['created'] for row in self.counts.values())

    def as_text(self):
        lines = ['Strety import summary' + (' (dry run, nothing was saved)' if self.dry_run
                                             else '')]
        width = max(len(name) for name in MODELS)
        for name, row in self.counts.items():
            lines.append(
                f'  {name.ljust(width)}  created {row["created"]:>4}   '
                f'skipped {row["skipped"]:>4}   errors {row["errors"]:>4}'
            )
        if self.headlines:
            lines.append(f'Headlines skipped ({len(self.headlines)}; they need a meeting in '
                         f'OpenEOS):')
            lines.extend(f'  - {team}: {title}' for team, title in self.headlines)
        if self.created_users:
            lines.append('Users created (no password set; send each a password reset):')
            lines.extend(f'  - {name} → {username}' for name, username in self.created_users)
        if self.unmatched_names:
            lines.append('Names not matched to a member (re-run with --create-users to add '
                         'them):')
            lines.extend(f'  - {name}' for name in self.unmatched_names)
        if self.errors:
            lines.append('Rows with errors:')
            lines.extend(f'  - {message}' for message in self.errors)
        if self.notes:
            lines.append('Notes:')
            lines.extend(f'  - {message}' for message in self.notes)
        return '\n'.join(lines)


class StretyImporter:
    def __init__(self, folder, organization, importing_user, *, create_users=False,
                 dry_run=False, include_archived=False):
        self.folder = folder
        self.organization = organization
        self.user = importing_user
        self.dry_run = dry_run
        self.include_archived = include_archived
        self.summary = ImportSummary()
        self.summary.dry_run = dry_run
        self.people = PeopleResolver(organization, importing_user, create_users)
        self._teams = {}

    def run(self):
        """Import the folder and return the summary. Raises StretyFormatError."""
        try:
            with transaction.atomic():
                self._import()
                if self.dry_run:
                    raise _DryRunRollback
        except _DryRunRollback:
            pass
        return self.summary

    # ── orchestration ────────────────────────────────────────────────────────

    def _import(self):
        vto_path, chart_path, team_dirs, ignored = locate_export(self.folder)
        for folder in ignored:
            self.summary.note(f'Folder "{folder.name}" skipped: no Strety files found in it.')
        if vto_path is not None:
            self._import_vto(vto_path)
        if chart_path is not None:
            self._import_chart(chart_path)
        for team_dir in team_dirs:
            self._import_team(team_dir)
        self.summary.note('Issue priority and owner are not carried: OpenEOS Issues have '
                          'neither field.')
        self.summary.unmatched_names = list(self.people.unmatched)
        self.summary.created_users = list(self.people.created)
        record_audit_event(
            'organization.imported', actor=self.user, organization=self.organization,
            details={'source': 'strety', 'dry_run': self.dry_run,
                     'created': self.summary.total_created()},
        )

    def _import_team(self, team_dir):
        team = self._team(team_dir.name)
        if (team_dir / 'goals.csv').is_file():
            self._import_goals(team, team_dir)
        if (team_dir / 'issues.csv').is_file():
            self._import_issues(team, team_dir / 'issues.csv')
        if (team_dir / 'todos.csv').is_file():
            self._import_todos(team, team_dir / 'todos.csv')
        if (team_dir / 'metrics.csv').is_file():
            self._import_metrics(team, team_dir / 'metrics.csv')
        if (team_dir / 'headlines.csv').is_file():
            self._skip_headlines(team, team_dir / 'headlines.csv')

    def _team(self, name):
        """The team called ``name``, counted once per run the first time it is seen."""
        if name not in self._teams:
            team, created = Team.objects.get_or_create(
                organization=self.organization, name=name
            )
            if created:
                self.summary.created('Teams')
                # The person running the import joins each team it creates, so what
                # landed is visible to them straight away (lists are per team).
                profile, _ = UserProfile.objects.get_or_create(user=self.user)
                profile.teams.add(team)
            else:
                self.summary.skipped('Teams')
            self._teams[name] = team
        return self._teams[name]

    def _team_for_row(self, row, column, folder_team):
        name = row.get(column, '').strip()
        return self._team(name) if name else folder_team

    @staticmethod
    def _set_created_at(obj, value):
        """``created_at`` is auto_now_add, so the export's timestamp goes in afterwards."""
        if value is not None:
            type(obj).objects.filter(pk=obj.pk).update(created_at=value)

    # ── goals.csv + milestones.csv ───────────────────────────────────────────

    def _import_goals(self, team, team_dir):
        rows = read_csv(team_dir / 'goals.csv', REQUIRED_COLUMNS['goals.csv'])
        milestones = {}
        if (team_dir / 'milestones.csv').is_file():
            for row in read_csv(team_dir / 'milestones.csv', REQUIRED_COLUMNS['milestones.csv']):
                milestones.setdefault(row['Goal Title'], []).append(row)
        for number, row in enumerate(rows, start=2):
            label = f'{team.name}/goals.csv line {number}'
            try:
                self._import_goal(team, row, milestones.pop(row['Title'], []), label)
            except ROW_ERRORS as exc:
                self.summary.error('Rocks', f'{label}: {exc}')
        for title, rows in milestones.items():
            self.summary.error('Rock milestones', f'{team.name}/milestones.csv: no goal '
                               f'titled "{title}" ({len(rows)} row(s))')

    def _import_goal(self, team, row, milestone_rows, label):
        title = row['Title']
        if not title:
            raise ValueError('Title is empty')
        if parse_bool(row.get('Archived')) and not self.include_archived:
            self.summary.skipped('Rocks')
            self.summary.skipped('Rock milestones', len(milestone_rows))
            return
        if Rock.objects.filter(team=team, title=title).exists():
            self.summary.skipped('Rocks')
            self.summary.skipped('Rock milestones', len(milestone_rows))
            return
        due_date = parse_date(row['Due Date'])
        if due_date is None:
            raise ValueError('Due Date is empty')
        completed_at = parse_datetime(row.get('Completed At'))
        status = self._rock_status(row['Status'], completed_at)
        description = '\n'.join(
            f'{column}: {row[column]}' for column in ('Target Value', 'Current Value')
            if row.get(column)
        )
        rock = Rock.objects.create(
            title=title, description=description, team=team,
            owner=self.people.resolve(row['Assignee'], required=True),
            created_by=self.people.resolve(row.get('Creator')),
            is_company_rock=parse_bool(row.get('Company Wide')),
            quarter=(due_date.month - 1) // 3 + 1, year=due_date.year,
            due_date=due_date, status=status,
        )
        self._set_created_at(rock, parse_datetime(row.get('Created At')))
        self.summary.created('Rocks')
        for position, milestone in enumerate(milestone_rows):
            try:
                self._import_milestone(rock, milestone, position)
            except ROW_ERRORS as exc:
                self.summary.error('Rock milestones', f'{label} milestone "{milestone["Title"]}":'
                                   f' {exc}')

    def _rock_status(self, raw, completed_at):
        if completed_at is not None:
            return Rock.STATUS_COMPLETE
        key = normalise(raw)
        if key in ROCK_STATUSES:
            return ROCK_STATUSES[key]
        self.summary.note(f'Goal status "{raw}" is not known; such Rocks are marked on track.')
        return Rock.STATUS_ON_TRACK

    def _import_milestone(self, rock, row, position):
        if not row['Title']:
            raise ValueError('Title is empty')
        complete = parse_bool(row.get('Completed'))
        completed_at = parse_datetime(row.get('Completed At'))
        order = row.get('Position')
        RockMilestone.objects.create(
            rock=rock, title=row['Title'], due_date=parse_date(row.get('Due Date')),
            is_complete=complete,
            completed_at=(completed_at or timezone.now()) if complete else None,
            order=int(order) if order else position,
        )
        self.summary.created('Rock milestones')

    # ── issues.csv ───────────────────────────────────────────────────────────

    def _import_issues(self, team, path):
        for number, row in enumerate(read_csv(path, REQUIRED_COLUMNS['issues.csv']), start=2):
            try:
                self._import_issue(team, row)
            except ROW_ERRORS as exc:
                self.summary.error('Issues', f'{team.name}/issues.csv line {number}: {exc}')

    def _import_issue(self, folder_team, row):
        title = row['Title']
        if not title:
            raise ValueError('Title is empty')
        team = self._team_for_row(row, 'Team', folder_team)
        if Issue.objects.filter(originating_team=team, title=title).exists():
            self.summary.skipped('Issues')
            return
        key = normalise(row['Issue Type'])
        if key not in ISSUE_TYPES:
            self.summary.note(f'Issue type "{row["Issue Type"]}" is not known; such Issues '
                              f'are short-term.')
        resolved_at = parse_datetime(row.get('Resolved At'))
        issue = Issue.objects.create(
            title=title, originating_team=team,
            created_by=self.people.resolve(row.get('Creator')),
            issue_type=ISSUE_TYPES.get(key, Issue.TYPE_SHORT_TERM),
            status=Issue.STATUS_RESOLVED if resolved_at else Issue.STATUS_OPEN,
        )
        self._set_created_at(issue, parse_datetime(row.get('Created At')))
        self.summary.created('Issues')

    # ── todos.csv ────────────────────────────────────────────────────────────

    def _import_todos(self, team, path):
        for number, row in enumerate(read_csv(path, REQUIRED_COLUMNS['todos.csv']), start=2):
            try:
                self._import_todo(team, row)
            except ROW_ERRORS as exc:
                self.summary.error('To-Dos', f'{team.name}/todos.csv line {number}: {exc}')

    def _import_todo(self, folder_team, row):
        title = row['Title']
        if not title:
            raise ValueError('Title is empty')
        team = self._team_for_row(row, 'Team', folder_team)
        if ToDo.objects.filter(team=team, title=title).exists():
            self.summary.skipped('To-Dos')
            return
        done = parse_bool(row.get('Completed'))
        fields = {
            'title': title, 'team': team,
            'owner': self.people.resolve(row['Assignee'], required=True),
            'status': ToDo.STATUS_COMPLETE if done else ToDo.STATUS_OPEN,
            'completed_at': (parse_datetime(row.get('Completed At')) or timezone.now())
            if done else None,
        }
        due_date = parse_date(row.get('Due Date'))
        if due_date is not None:
            fields['due_date'] = due_date
        todo = ToDo.objects.create(**fields)
        self._set_created_at(todo, parse_datetime(row.get('Created At')))
        self.summary.created('To-Dos')

    # ── metrics.csv ──────────────────────────────────────────────────────────

    def _import_metrics(self, team, path):
        rows = read_csv(path, REQUIRED_COLUMNS['metrics.csv'])
        if not rows:
            return
        scorecard, created = Scorecard.objects.get_or_create(
            team=team, name=f'{team.name} Scorecard'
        )
        if created:
            self.summary.created('Scorecards')
        else:
            self.summary.skipped('Scorecards')
        for number, row in enumerate(rows, start=2):
            try:
                self._import_metric(scorecard, row, number - 2)
            except ROW_ERRORS as exc:
                self.summary.error('Scorecard metrics',
                                   f'{team.name}/metrics.csv line {number}: {exc}')

    def _import_metric(self, scorecard, row, order):
        title = row['Title']
        if not title:
            raise ValueError('Title is empty')
        if ScorecardMetric.objects.filter(scorecard=scorecard, name=title).exists():
            self.summary.skipped('Scorecard metrics')
            if row.get('Latest Value') and row.get('Latest Entry Date'):
                self.summary.skipped('Scorecard entries')
            return
        goal_value = parse_decimal(row.get('Target Value'))
        if goal_value is None:
            goal_value = Decimal(0)
            self.summary.note('Metrics without a Target Value were given a goal of 0.')
        metric = ScorecardMetric.objects.create(
            scorecard=scorecard, name=title, order=order,
            owner=self.people.resolve(row.get('Assignee'), required=True),
            metric_type=self._metric_type(row['Number Format'], goal_value),
            goal_value=goal_value,
            goal_direction=self._goal_direction(row.get('Target Type')),
            frequency=self._frequency(row.get('Checkin Frequency')),
        )
        self.summary.created('Scorecard metrics')
        value = parse_decimal(row.get('Latest Value'))
        entry_date = parse_date(row.get('Latest Entry Date'))
        if value is not None and entry_date is not None:
            if metric.frequency == ScorecardMetric.FREQ_WEEKLY:
                period_start = entry_date - timedelta(days=entry_date.weekday())
            else:
                period_start = entry_date.replace(day=1)
            ScorecardEntry.objects.create(
                metric=metric, period_start=period_start, value=value,
                entered_by=self.people.resolve(row.get('Creator')) or self.user,
            )
            self.summary.created('Scorecard entries')

    def _metric_type(self, raw, goal_value):
        key = normalise(raw)
        if key not in METRIC_TYPES:
            self.summary.note(f'Number format "{raw}" is not known; such metrics are integers.')
        metric_type = METRIC_TYPES.get(key, ScorecardMetric.TYPE_INTEGER)
        if metric_type == ScorecardMetric.TYPE_INTEGER and goal_value != goal_value.to_integral():
            return ScorecardMetric.TYPE_FLOAT
        return metric_type

    def _goal_direction(self, raw):
        key = normalise(raw)
        if key and key not in GOAL_DIRECTIONS:
            self.summary.note(f'Target type "{raw}" is not known; such metrics are "at or '
                              f'above goal".')
        return GOAL_DIRECTIONS.get(key, ScorecardMetric.DIR_ABOVE)

    def _frequency(self, raw):
        key = normalise(raw)
        if not key:
            return ScorecardMetric.FREQ_WEEKLY
        if key not in FREQUENCIES:
            self.summary.note(f'Check-in frequency "{raw}" is not available in OpenEOS; such '
                              f'metrics are monthly.')
        return FREQUENCIES.get(key, ScorecardMetric.FREQ_MONTHLY)

    # ── headlines.csv ────────────────────────────────────────────────────────

    def _skip_headlines(self, team, path):
        for row in read_csv(path, REQUIRED_COLUMNS['headlines.csv']):
            if row['Title']:
                self.summary.headlines.append((team.name, row['Title']))

    # ── vto.md ───────────────────────────────────────────────────────────────

    def _import_vto(self, path):
        data = parse_vto_markdown(path.read_text(encoding='utf-8'))
        vto = VTO.for_org(self.organization)
        existing = {normalise(name) for name in vto.core_values.values_list('name', flat=True)}
        for order, (name, description) in enumerate(data['core_values']):
            if normalise(name) in existing:
                self.summary.skipped('VTO core values')
                continue
            VTOCoreValue.objects.create(
                vto=vto, name=name[:100], description=description, order=order
            )
            self.summary.created('VTO core values')
        for key, content in self._vto_sections(data).items():
            if not content:
                continue
            section, created = VTOSection.objects.get_or_create(
                vto=vto, key=key, defaults={
                    'content': content, 'last_edited_by': self.user,
                    'last_edited_at': timezone.now(),
                },
            )
            if created:
                self.summary.created('VTO sections')
            elif section.content.strip():
                self.summary.skipped('VTO sections')
            else:
                section.content = content
                section.last_edited_by = self.user
                section.last_edited_at = timezone.now()
                section.save()
                self.summary.created('VTO sections')

    def _vto_sections(self, data):
        sections = {}
        blocks = data['sections']
        focus = dict(blocks.get('core_focus', {}).get('fields', []))
        sections[SectionKey.CORE_FOCUS_PURPOSE] = strip_markdown(focus.get('Purpose', ''))
        sections[SectionKey.CORE_FOCUS_NICHE] = strip_markdown(focus.get('Niche', ''))
        sections[SectionKey.TEN_YEAR_TARGET] = ' '.join(
            blocks.get('ten_year_target', {}).get('paragraphs', [])
        )

        strategy = dict(blocks.get('strategy', {}).get('fields', []))
        sections[SectionKey.TARGET_MARKET] = strip_markdown(strategy.get('Target Market', ''))
        sections[SectionKey.PROVEN_PROCESS] = strip_markdown(strategy.get('Proven Process', ''))
        sections[SectionKey.GUARANTEE] = strip_markdown(strategy.get('Guarantee', ''))
        uniques = data['uniques']
        if len(uniques) > 3:
            self.summary.note(f'{len(uniques)} uniques found in vto.md; only the first three '
                              f'were imported.')
        unique_keys = (SectionKey.THREE_UNIQUES_1, SectionKey.THREE_UNIQUES_2,
                       SectionKey.THREE_UNIQUES_3)
        for key, (title, text) in zip(unique_keys, uniques):
            sections[key] = f'{title} — {text}' if title and text else (title or text)

        three_year = blocks.get('three_year_picture', {})
        sections[SectionKey.THREE_YEAR_PICTURE] = self._measurables(three_year.get('fields', []))
        sections[SectionKey.THREE_YEAR_GOALS] = self._goals_text(three_year)

        one_year = blocks.get('one_year_plan', {})
        fields = one_year.get('fields', [])
        sections[SectionKey.ONE_YEAR_REVENUE] = dict(fields).get('Revenue', '')
        sections[SectionKey.ONE_YEAR_PROFIT] = dict(fields).get('Profit', '')
        remaining = [(label, value) for label, value in fields
                     if label not in ('Revenue', 'Profit')]
        sections[SectionKey.ONE_YEAR_GOALS] = '\n'.join(
            part for part in (self._measurables(remaining), self._goals_text(one_year)) if part
        )
        return sections

    @staticmethod
    def _measurables(fields):
        return '\n'.join(f'{label}: {value}' for label, value in fields if value)

    @staticmethod
    def _goals_text(block):
        bullets = list(block.get('bullets', []))
        for name, sub in block.get('subsections', {}).items():
            if name.startswith('goal'):
                bullets.extend(sub['bullets'])
        lines = []
        for bullet in bullets:
            title, status, text = parse_goal_bullet(bullet)
            prefix = f'{title} ({status})' if status else title
            lines.append(f'- {prefix} — {text}' if text else f'- {prefix}')
        return '\n'.join(lines)

    # ── accountability chart ─────────────────────────────────────────────────

    def _import_chart(self, path):
        rows = read_csv(path, REQUIRED_COLUMNS['chart'])
        nodes = {
            normalise(node.name): node
            for node in AccountabilityNode.objects.filter(organization=self.organization)
        }
        created = []
        for number, row in enumerate(rows, start=2):
            name = row['Role'][:100]
            if not name:
                self.summary.error('Accountability seats', f'{path.name} line {number}: Role '
                                   f'is empty')
                continue
            if normalise(name) in nodes:
                self.summary.skipped('Accountability seats')
                continue
            holders = split_list(row['Seat Holder(s)'])
            holders = [holder for holder in holders if not is_blank_person(holder)]
            node = AccountabilityNode.objects.create(
                organization=self.organization, name=name, order=number,
                node_type=(AccountabilityNode.TYPE_DEPARTMENT if 'box' in normalise(name).split()
                           else AccountabilityNode.TYPE_SEAT),
                owner=self.people.resolve(holders[0]) if holders else None,
            )
            if len(holders) > 1:
                self.summary.note(f'Seat "{name}" has more than one holder; only '
                                  f'"{holders[0]}" was kept (also: {", ".join(holders[1:])}).')
            nodes[normalise(name)] = node
            created.append((node, row))
            self.summary.created('Accountability seats')
            for order, description in enumerate(split_list(row.get('Responsibilities', ''))):
                AccountabilityRole.objects.create(
                    node=node, description=description[:200], order=order
                )
                self.summary.created('Accountability roles')
        for node, row in created:
            reports_to = row['Reports To']
            if not reports_to:
                continue
            parent = nodes.get(normalise(reports_to))
            if parent is None or parent == node:
                self.summary.note(f'Seat "{node.name}" reports to "{reports_to}", which is not '
                                  f'in the chart; it was left at the top level.')
                continue
            node.parent = parent
            node.save(update_fields=['parent'])


def import_strety(folder, organization, importing_user, **options):
    """Convenience wrapper: build an importer, run it and return the summary."""
    return StretyImporter(folder, organization, importing_user, **options).run()


__all__ = ['ImportSummary', 'StretyFormatError', 'StretyImporter', 'import_strety']
