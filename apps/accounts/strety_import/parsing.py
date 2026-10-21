"""Readers for the files in a Strety export. Nothing in here touches the database.

A native Strety export is a folder holding ``vto.md``, an
``accountability_chart - <name>.csv`` and one sub-folder per team, each with any
of ``goals.csv``, ``issues.csv``, ``todos.csv``, ``metrics.csv`` and
``headlines.csv``. We also accept an optional ``milestones.csv`` beside
``goals.csv``, which Strety does not write itself.
"""
import csv
import html
import re
from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


class StretyFormatError(Exception):
    """The export is missing, malformed or ambiguous. Reported as a CommandError."""


TEAM_FILES = (
    'goals.csv', 'milestones.csv', 'issues.csv', 'todos.csv', 'metrics.csv', 'headlines.csv',
)

REQUIRED_COLUMNS = {
    'goals.csv': ('Title', 'Status', 'Assignee', 'Due Date'),
    'milestones.csv': ('Goal Title', 'Title'),
    'issues.csv': ('Title', 'Issue Type'),
    'todos.csv': ('Title', 'Assignee'),
    'metrics.csv': ('Title', 'Number Format'),
    'headlines.csv': ('Title',),
    'chart': ('Level', 'Role', 'Reports To', 'Seat Holder(s)'),
}

BLANK_PEOPLE = {'', '(unassigned)', 'unassigned', 'none', '-'}


# ── Folder layout ────────────────────────────────────────────────────────────

def locate_export(folder):
    """Return ``(vto_path, chart_path, team_dirs, ignored_dirs)`` for an export folder.

    ``vto.md`` and the chart normally sit at the top level. Strety has also been
    seen to put them in a folder named after the organisation beside the team
    folders, so a sub-folder with no team CSVs is searched as well.
    """
    top = Path(folder)
    if not top.is_dir():
        raise StretyFormatError(f'{top} is not a folder.')

    subdirs = sorted(d for d in top.iterdir() if d.is_dir() and not d.name.startswith('.'))
    team_dirs = [d for d in subdirs if any((d / name).is_file() for name in TEAM_FILES)]
    other_dirs = [d for d in subdirs if d not in team_dirs]

    vto_path = _single_file([top] + other_dirs, 'vto.md')
    chart_path = _single_file([top] + other_dirs, 'accountability_chart*.csv')

    ignored = [
        d for d in other_dirs
        if d not in {p.parent for p in (vto_path, chart_path) if p is not None}
    ]
    if vto_path is None and chart_path is None and not team_dirs:
        raise StretyFormatError(f'No Strety export files found in {top}.')
    return vto_path, chart_path, team_dirs, ignored


def _single_file(dirs, pattern):
    found = sorted(p for d in dirs for p in d.glob(pattern) if p.is_file())
    if len(found) > 1:
        names = ', '.join(str(p) for p in found)
        raise StretyFormatError(
            f'Found {pattern} in more than one place ({names}); point the command at the '
            f'folder for a single organisation.'
        )
    return found[0] if found else None


# ── CSV ──────────────────────────────────────────────────────────────────────

def read_csv(path, required_columns):
    """Return the rows of a CSV as stripped dicts, checking the header first."""
    try:
        with Path(path).open(newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames
            if not header:
                raise StretyFormatError(f'{path} is empty.')
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise StretyFormatError(
                    f'{path} is missing column(s): {", ".join(missing)}.'
                )
            rows = []
            for row in reader:
                if None in row:
                    raise StretyFormatError(
                        f'{path} line {reader.line_num} has more values than the header.'
                    )
                rows.append({key: (value or '').strip() for key, value in row.items()})
    except (csv.Error, UnicodeDecodeError) as exc:
        raise StretyFormatError(f'{path} could not be read as CSV: {exc}') from exc
    return rows


# ── Scalars ──────────────────────────────────────────────────────────────────

def parse_date(value):
    """``YYYY-MM-DD`` (a timestamp is accepted and truncated) → date, or None when blank."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f'"{value}" is not a date (expected YYYY-MM-DD)') from exc


def parse_datetime(value):
    """``YYYY-MM-DD HH:MM`` (seconds and a T separator are fine) → aware UTC datetime."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'"{value}" is not a timestamp (expected YYYY-MM-DD HH:MM)') from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def parse_bool(value):
    return (value or '').strip().lower() in {'yes', 'y', 'true', '1'}


def parse_decimal(value):
    """A number as Strety writes it ("$25,000", "80%", "Yes") → Decimal, or None when blank."""
    raw = (value or '').strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {'yes', 'true'}:
        return Decimal(1)
    if lowered in {'no', 'false'}:
        return Decimal(0)
    cleaned = re.sub(r'[^0-9.\-]', '', raw)
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f'"{raw}" is not a number') from exc


def normalise(value):
    """Lower-case with punctuation collapsed to single spaces, for matching labels."""
    return ' '.join(re.sub(r'[^0-9a-z]+', ' ', (value or '').lower()).split())


def is_blank_person(name):
    return (name or '').strip().lower() in BLANK_PEOPLE


def split_list(value):
    """Split "a; b" or "a, b" or one-per-line text into a list of stripped parts."""
    value = (value or '').strip()
    if not value:
        return []
    if '\n' in value:
        separator = '\n'
    elif ';' in value:
        separator = ';'
    else:
        separator = ','
    return [part.strip() for part in value.split(separator) if part.strip()]


# ── vto.md ───────────────────────────────────────────────────────────────────

_TITLE_RE = re.compile(r'^#\s+(?P<name>.*?)\s*(?:V/TO.*)?$')
_FIELD_RE = re.compile(r'^\*\*(?P<label>[^*]+?):\*\*\s*(?P<value>.*)$')
_BULLET_RE = re.compile(r'^[-*]\s+(?P<text>.*)$')
_CORE_VALUE_RE = re.compile(
    r'^\d+\.\s+\*\*(?P<name>.+?)\*\*\s*(?:\(id:\s*`[^`]*`\))?\s*(?:[—–-]+\s*(?P<text>.*))?$'
)
_UNIQUE_RE = re.compile(r'^\*\*(?P<title>.*?)\*\*\s*(?:[—–-]+\s*(?P<text>.*))?$')
_GOAL_RE = re.compile(r'^(?P<title>.*?)\s+[—–-]+\s+_(?P<status>[^_]*)_\s+[—–-]+\s+(?P<text>.*)$')

SECTION_ALIASES = {
    'core values': 'core_values',
    'core focus': 'core_focus',
    '10 year target': 'ten_year_target',
    'ten year target': 'ten_year_target',
    '3 year picture': 'three_year_picture',
    'three year picture': 'three_year_picture',
    'strategy': 'strategy',
    'marketing strategy': 'strategy',
    '1 year plan': 'one_year_plan',
    'one year plan': 'one_year_plan',
    'quarterly rocks': 'quarterly_rocks',
    'issues list': 'issues_list',
}


def _new_block():
    return {'fields': [], 'bullets': [], 'paragraphs': [], 'subsections': {}}


def parse_vto_markdown(text):
    """Parse ``vto.md`` into plain data.

    Returns a dict with ``organization_name``, ``core_values`` (list of
    ``(name, description)``), ``uniques`` (list of ``(title, text)``) and
    ``sections``: one block per known ``##`` heading holding ``fields`` (ordered
    ``(label, value)``), ``bullets``, ``paragraphs`` and ``subsections`` (same
    shape, keyed by the normalised ``###`` heading).
    """
    result = {'organization_name': '', 'core_values': [], 'uniques': [], 'sections': {}}
    section = None
    block = None
    for raw_line in html.unescape(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith('---') or re.fullmatch(r'_.*_', line):
            continue
        if line.startswith('# ') and not result['organization_name']:
            result['organization_name'] = _TITLE_RE.match(line).group('name').strip()
            continue
        if line.startswith('## '):
            heading = normalise(line[3:].split('(')[0])
            section = next(
                (key for alias, key in SECTION_ALIASES.items() if heading.startswith(alias)),
                None,
            )
            block = None
            if section is not None:
                block = result['sections'].setdefault(section, _new_block())
            continue
        if block is None:
            continue
        if line.startswith('### '):
            name = normalise(line[4:])
            block = result['sections'][section]['subsections'].setdefault(name, _new_block())
            continue
        _add_line(result, section, block, line)
    return result


def _add_line(result, section, block, line):
    if section == 'core_values':
        match = _CORE_VALUE_RE.match(line)
        if match:
            result['core_values'].append(
                (match.group('name').strip(), (match.group('text') or '').strip())
            )
            return
    field = _FIELD_RE.match(line)
    if field:
        block['fields'].append((field.group('label').strip(), field.group('value').strip()))
        return
    bullet = _BULLET_RE.match(line)
    if bullet:
        text = bullet.group('text').strip()
        if section == 'strategy':
            unique = _UNIQUE_RE.match(text)
            if unique:
                result['uniques'].append(
                    (unique.group('title').strip(), (unique.group('text') or '').strip())
                )
                return
        block['bullets'].append(text)
        return
    block['paragraphs'].append(strip_markdown(line))


def strip_markdown(text):
    return re.sub(r'\*\*(.*?)\*\*', r'\1', text).strip()


def parse_goal_bullet(text):
    """``Title — _open_ — detail`` → ``(title, status, detail)``; plain bullets keep the text."""
    match = _GOAL_RE.match(text)
    if match:
        return match.group('title').strip(), match.group('status').strip(), match.group('text')
    return text.strip(), '', ''
