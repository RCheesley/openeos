"""Runs the axe-core rules engine over the main pages, signed out and signed in.

Every violation of a WCAG 2.2 level A or AA rule fails the test unless
``known_violations.toml`` lists that rule for that page. An entry in that file
that no longer matches anything fails too, so the list can only shrink.
"""
import json
import os
import tomllib
from collections import defaultdict
from pathlib import Path

from .base import BrowserTestCase

try:
    from axe_playwright_python.sync_playwright import Axe
except ImportError:  # BrowserTestCase skips the class with install instructions
    Axe = None

KNOWN_VIOLATIONS_FILE = Path(__file__).parent / 'known_violations.toml'

# axe-core tags each rule with the success criteria it tests. These five cover
# WCAG 2.0, 2.1 and 2.2 at levels A and AA (2.2 added no level A rules to axe).
WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
AXE_OPTIONS = {
    'runOnly': {'type': 'tag', 'values': WCAG_TAGS},
    'resultTypes': ['violations', 'incomplete'],
}

SIGNED_OUT_PAGES = [
    ('sign-in', '/accounts/login/'),
    ('password-reset', '/accounts/password_reset/'),
]


def signed_in_pages(ids):
    return [
        ('dashboard', '/'),
        ('priorities-list', '/rocks/'),
        ('priority-detail', f'/rocks/{ids["rock"]}/'),
        ('priority-form', '/rocks/new/'),
        ('blockers-list', '/issues/'),
        ('blocker-detail', f'/issues/{ids["issue"]}/'),
        ('actions-list', '/todos/'),
        ('action-form', '/todos/new/'),
        ('metrics-board-list', '/scorecards/'),
        ('metrics-board', f'/scorecards/{ids["scorecard"]}/'),
        ('metrics-entry', f'/scorecards/{ids["scorecard"]}/enter/'),
        ('meetings-list', '/meetings/'),
        ('meeting-runner', f'/meetings/{ids["meeting"]}/'),
        ('vision', '/vision/'),
        ('roles-chart', '/accountability/'),
        ('organisation-settings', '/org/settings/'),
        ('terminology', '/org/settings/terminology/'),
        ('profile', '/profile/'),
    ]


def load_known_violations():
    """Return ``{(rule, page): reason}`` from the reviewed list."""
    with KNOWN_VIOLATIONS_FILE.open('rb') as handle:
        entries = tomllib.load(handle).get('known', [])
    known = {}
    for entry in entries:
        extra = set(entry) - {'rule', 'page', 'reason'}
        if extra or not all(entry.get(key, '').strip() for key in ('rule', 'page', 'reason')):
            raise ValueError(f'{KNOWN_VIOLATIONS_FILE.name}: every entry needs a rule, a page and a reason: {entry}')
        key = (entry['rule'], entry['page'])
        if key in known:
            raise ValueError(f'{KNOWN_VIOLATIONS_FILE.name}: {key} is listed twice')
        known[key] = entry['reason']
    return known


class PageAccessibilityTest(BrowserTestCase):
    def test_pages_have_no_new_wcag_violations(self):
        axe = Axe()
        found = {}       # page -> list of axe violation dicts
        incomplete = {}  # page -> list of axe "needs review" dicts

        def check(name, path):
            self.open(path)
            response = axe.run(self.page, options=AXE_OPTIONS).response
            found[name] = response['violations']
            incomplete[name] = response['incomplete']
            return response

        # A11Y_PAGES=sign-in,dashboard checks just those pages, for a quick
        # local run while fixing one of them.
        only = {name.strip() for name in os.environ.get('A11Y_PAGES', '').split(',') if name.strip()}
        everything = SIGNED_OUT_PAGES + signed_in_pages(self.ids)
        unknown = only - {name for name, _ in everything}
        self.assertFalse(unknown, f'A11Y_PAGES names pages that do not exist: {sorted(unknown)}')

        response = None
        for name, path in SIGNED_OUT_PAGES:
            if not only or name in only:
                response = check(name, path)
        self.sign_in()
        for name, path in signed_in_pages(self.ids):
            if not only or name in only:
                response = check(name, path)
        engine = response['testEngine']['version']

        known = load_known_violations()
        seen = {(violation['id'], page) for page, violations in found.items() for violation in violations}
        new = sorted(seen - set(known))
        stale = sorted(key for key in set(known) - seen if key[1] in found)
        report = build_report(found, incomplete, known, new, stale, engine)
        write_report(report, found, incomplete)

        if new or stale:
            self.fail('\n' + report)


def build_report(found, incomplete, known, new, stale, engine):
    """A Markdown summary: what is new, what is known, and where each one is."""
    by_rule = defaultdict(dict)
    details = {}
    for page, violations in found.items():
        for violation in violations:
            by_rule[violation['id']][page] = violation['nodes']
            details[violation['id']] = violation
    total_nodes = sum(len(nodes) for pages in by_rule.values() for nodes in pages.values())

    lines = [
        '## Accessibility check',
        '',
        f'axe-core {engine}, rule tags {", ".join(WCAG_TAGS)}, {len(found)} pages.',
        f'{len(by_rule)} rules violated, {total_nodes} elements in total; '
        f'{len(new)} new rule/page pairs, {len(stale)} listed pairs no longer found.',
        '',
    ]
    if new:
        lines += ['### New violations (not in known_violations.toml)', '']
        for rule, page in new:
            nodes = by_rule[rule][page]
            lines.append(f'- **{rule}** on **{page}**: {len(nodes)} element(s). {details[rule]["help"]}')
            for node in nodes[:5]:
                lines.append(f'    - `{" ".join(str(part) for part in node["target"])}`')
                lines.append(f'      {first_line(node.get("failureSummary", ""))}')
            if len(nodes) > 5:
                lines.append(f'    - and {len(nodes) - 5} more')
        lines += ['', 'Fix these, or add them to accessibility/known_violations.toml with a reason.', '']
    if stale:
        lines += ['### Listed as known but no longer found', '']
        lines += [f'- **{rule}** on **{page}**' for rule, page in stale]
        lines += ['', 'Remove these entries from accessibility/known_violations.toml.', '']
    if by_rule:
        lines += ['### All violations by rule', '']
        for rule in sorted(by_rule):
            pages = by_rule[rule]
            count = sum(len(nodes) for nodes in pages.values())
            violation = details[rule]
            lines.append(
                f'- **{rule}** ({violation["impact"]}): {count} element(s) on {len(pages)} page(s). '
                f'{violation["help"]}. {violation["helpUrl"]}'
            )
            for page in sorted(pages):
                status = 'known' if (rule, page) in known else 'NEW'
                lines.append(f'    - {page}: {len(pages[page])} ({status})')
        lines.append('')
    needs_review = {page: sum(len(item['nodes']) for item in items) for page, items in incomplete.items()}
    if any(needs_review.values()):
        lines += [
            '### Needs a person to look',
            '',
            'axe-core could not decide on these (text over a gradient or image, for example). '
            'They do not fail the check; the elements are in the JSON report.',
            '',
        ]
        lines += [f'- {page}: {count}' for page, count in needs_review.items() if count]
        lines.append('')
    return '\n'.join(lines)


def first_line(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ' '.join(lines[:2])


def write_report(report, found, incomplete):
    """Save the summary and the full axe output when A11Y_REPORT_DIR is set (CI does)."""
    directory = os.environ.get('A11Y_REPORT_DIR')
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / 'accessibility-report.md').write_text(report, encoding='utf-8')
    (target / 'accessibility-report.json').write_text(
        json.dumps({'violations': found, 'incomplete': incomplete}, indent=2), encoding='utf-8',
    )
