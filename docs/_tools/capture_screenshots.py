"""Take every screenshot the documentation uses, in one scripted run.

The script signs in to a throwaway instance loaded with the Harbour Lights
demo data (see seed_demo.py), walks through the tasks the how-to guides
describe, and saves one PNG per step into docs/_static/screenshots/. It also
writes docs/_tools/screenshots.json, the manifest that maps each image to the
page and state it shows.

The run changes data as it goes (it adds an Action, runs a Weekly Meeting and
so on), so always start from a freshly seeded, empty database. docs/README.md
has the commands.

    python capture_screenshots.py --base-url http://localhost:8040 --out ../_static/screenshots

Needs Playwright (with Chromium) and Pillow. The official Playwright Python
container image has the browser already.
"""
import argparse
import base64
import hashlib
import hmac
import json
import struct
import time
from datetime import date, timedelta
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

PASSWORD = 'harbour-lights-demo'
VIEWPORT = {'width': 1280, 'height': 900}
SCALE = 2
MAX_BYTES = 200 * 1024
# The page content without the navigation bar and footer.
CONTENT = 'main > .container-fluid'


def totp(secret_base32, step=30, digits=6):
    """The current time-based one-time code for an authenticator key."""
    key = base64.b32decode(secret_base32.replace(' ', '').upper())
    counter = struct.pack('>Q', int(time.time()) // step)
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** digits).zfill(digits)


def wait_for_next_code(step=30):
    """A code works once, so wait for the next 30-second window before reusing a key."""
    time.sleep(step - (time.time() % step) + 1)


def optimise(path):
    """Reduce the PNG to an indexed palette; screenshots of a flat interface lose nothing visible."""
    for colours in (256, 128, 64):
        image = Image.open(path).convert('RGB')
        image = image.quantize(colors=colours, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        image.save(path, optimize=True)
        if path.stat().st_size <= MAX_BYTES:
            return


class Capture:
    def __init__(self, browser, base_url, out_dir):
        self.browser = browser
        self.base_url = base_url.rstrip('/')
        self.out_dir = out_dir
        self.manifest = []

    def sign_in(self, username):
        context = self.browser.new_context(
            viewport=VIEWPORT, device_scale_factor=SCALE, color_scheme='light',
            locale='en-GB', timezone_id='UTC', accept_downloads=True,
        )
        page = context.new_page()
        page.username = username
        page.goto(self.base_url + '/accounts/login/')
        page.fill('#id_username', username)
        page.fill('#id_password', PASSWORD)
        return page

    def go(self, page, path):
        page.goto(self.base_url + path)

    def shot(self, page, name, state, *selectors, pad=16):
        """Save ``name``.png, cropped to the union of ``selectors`` (the whole view when none)."""
        page.evaluate('window.scrollTo(0, 0)')
        page.mouse.move(0, 0)
        page.wait_for_timeout(250)
        path = self.out_dir / f'{name}.png'
        if selectors == (CONTENT,):
            pad = 0
        if selectors:
            boxes = []
            for selector in selectors:
                locator = page.locator(selector) if isinstance(selector, str) else selector
                box = locator.first.bounding_box()
                if box is None:
                    raise RuntimeError(f'{name}: nothing matches {selector!r}')
                boxes.append(box)
            left = max(0, min(b['x'] for b in boxes) - pad)
            top = max(0, min(b['y'] for b in boxes) - pad)
            right = max(b['x'] + b['width'] for b in boxes) + pad
            bottom = max(b['y'] + b['height'] for b in boxes) + pad
            page.screenshot(path=str(path), full_page=True, clip={
                'x': left, 'y': top, 'width': right - left, 'height': bottom - top,
            })
        else:
            page.screenshot(path=str(path))
        optimise(path)
        self.manifest.append({
            'file': path.name,
            'path': page.url.replace(self.base_url, ''),
            'signed_in_as': getattr(page, 'username', ''),
            'shows': state,
        })
        print(f'{path.name:44} {path.stat().st_size // 1024:>4} KB  {state}')


def card(page, heading):
    """The card whose small heading reads ``heading``."""
    return page.locator('main .card').filter(
        has=page.locator('h5, h6, .card-header', has_text=heading)
    )


def run(cap):
    today = date.today()

    # ── Sign in (Tom Reyes, a Team Member in Operations) ─────────────────────
    tom = cap.sign_in('tom')
    cap.shot(tom, 'sign-in', 'The sign-in page with a username and password filled in',
             '.card', 'h1', pad=24)
    tom.click('button[type=submit]')
    cap.shot(tom, 'dashboard', 'The Dashboard for a Team Member, top row of cards',
             'main h1', tom.locator('main .card').nth(0), tom.locator('main .card').nth(2))

    # ── Actions ──────────────────────────────────────────────────────────────
    cap.go(tom, '/todos/')
    cap.shot(tom, 'action-list', 'My Actions, open Actions for the active team', CONTENT)
    tom.get_by_role('link', name='New Action').first.click()
    tom.fill('[name=title]', 'Measure the fuel dock queue on Saturday')
    tom.fill('[name=description]', 'Count the boats waiting at 10:00, 12:00 and 14:00.')
    tom.select_option('[name=linked_rock]', label='Cut fuel dock waiting time to ten minutes')
    cap.shot(tom, 'action-form', 'The Create Action form, filled in', 'main .card', 'main h1')
    tom.get_by_role('button', name='Create Action').click()
    cap.shot(tom, 'action-created', 'My Actions after creating an Action, with the confirmation message', CONTENT)
    row = tom.locator('li.list-group-item', has_text='Check the lifebuoy stations')
    cap.shot(tom, 'action-row', 'One Action in the list: the circle, the title, the due date and the menu', row)
    row.locator('button[title="Mark complete"]').click()
    cap.go(tom, '/todos/?view=mine&status=complete')
    cap.shot(tom, 'action-completed', 'My Actions with the Complete filter selected', CONTENT)

    # ── Priorities, Steps and check-ins ──────────────────────────────────────
    cap.go(tom, '/rocks/')
    cap.shot(tom, 'priority-list', 'The Priorities list for the Operations team, current quarter', CONTENT)
    tom.get_by_role('link', name='Cut fuel dock waiting time to ten minutes').first.click()
    header = tom.locator('main h1').locator('xpath=ancestor::div[contains(@class,"d-flex")][1]')
    cap.shot(tom, 'priority-detail', 'A Priority: status, owner, due date, description and Steps',
             header, card(tom, 'Description'), card(tom, 'Steps'))
    step = tom.locator('.card li, .card .d-flex', has_text='Add a second card reader').last
    step.locator('button[title="Toggle complete"]').click()
    cap.shot(tom, 'priority-step-done', 'The Steps card after ticking a second Step', card(tom, 'Steps'))
    checkins = card(tom, 'Check-ins')
    checkins.locator('label', has_text='On Track').click()
    checkins.locator('[name=note]').fill('Second card reader fitted. Saturday wait was 13 minutes.')
    cap.shot(tom, 'priority-checkin-form', 'The Check-ins card with On Track chosen and a note typed', checkins)
    checkins.get_by_role('button', name='Add Check-in').click()
    cap.shot(tom, 'priority-checkin-saved', 'The Check-ins card with the new check-in at the top',
             '.alert', card(tom, 'Check-ins'))
    tom.locator('main .dropdown > button').first.click()
    cap.shot(tom, 'priority-status-menu', 'The three-dot menu on a Priority, open',
             header, tom.locator('.dropdown-menu.show'))
    tom.keyboard.press('Escape')

    # ── Create a Priority and add Steps (Priyanka Nair, Operations) ──────────
    priyanka = cap.sign_in('priyanka')
    priyanka.click('button[type=submit]')
    priyanka.locator('nav .nav-link', has=priyanka.locator('.bi-people-fill')).click()
    cap.shot(priyanka, 'team-switcher', 'The team menu in the navigation bar, open, with two teams',
             priyanka.locator('nav .nav-link', has=priyanka.locator('.bi-people-fill')),
             priyanka.locator('.dropdown-menu.show'))
    priyanka.locator('.dropdown-menu.show button', has_text='Operations').click()
    cap.go(priyanka, '/rocks/')
    priyanka.get_by_role('link', name='New Priority').first.click()
    priyanka.fill('[name=title]', 'Open the winter storage yard')
    priyanka.fill('[name=description]', 'Forty boats ashore, each on a numbered cradle, by the end of the quarter.')
    # The owner is the person who can add Steps and check in, so she owns this one herself.
    priyanka.select_option('[name=owner]', label='priyanka')
    cap.shot(priyanka, 'priority-form', 'The Create Priority form, filled in', 'main .card', 'main h1')
    priyanka.get_by_role('button', name='Create Priority').click()
    steps = card(priyanka, 'Steps')
    steps.locator('[name=title]').fill('Mark out the cradle positions')
    steps.locator('[name=due_date]').fill((today + timedelta(days=10)).isoformat())
    cap.shot(priyanka, 'priority-add-step', 'A new Priority with the first Step typed into the Steps card',
             '.alert', priyanka.locator('main h1').locator('xpath=ancestor::div[contains(@class,"d-flex")][1]'), steps)
    steps.get_by_role('button', name='Add').click()
    steps = card(priyanka, 'Steps')
    steps.locator('[name=title]').fill('Book the crane for lifting week')
    steps.get_by_role('button', name='Add').click()
    cap.shot(priyanka, 'priority-steps-added', 'The Steps card with two Steps added', card(priyanka, 'Steps'))

    # ── Blockers ─────────────────────────────────────────────────────────────
    cap.go(tom, '/issues/')
    cap.shot(tom, 'blocker-list', 'The list of open Blockers for the Operations team',
             tom.locator('main .card, main .list-group, main table').first)
    tom.get_by_role('link', name='New Blocker').first.click()
    tom.fill('[name=title]', 'Fuel dock queue blocks the slipway')
    tom.fill('[name=description]', 'On busy Saturdays the queue stops boats launching from the slipway.')
    tom.locator('label', has_text='Cut fuel dock waiting time to ten minutes').click()
    cap.shot(tom, 'blocker-form', 'The Create Blocker form, filled in', 'main .card', 'main h1')
    tom.get_by_role('button', name='Create Blocker').click()
    cap.shot(tom, 'blocker-detail', 'A new Blocker with its details, activity and status buttons', CONTENT)
    status = card(tom, 'Update Status')
    status.locator('[name=resolution_notes]:visible').fill(
        'Queue now forms along the east wall. Sign moved to the quay entrance.'
    )
    cap.shot(tom, 'blocker-resolve', 'The Update Status card with a resolution note typed', status)
    status.get_by_role('button', name='Mark Resolved').click()
    cap.shot(tom, 'blocker-resolved', 'A resolved Blocker showing the Resolution card', CONTENT)

    # ── Metrics Board ────────────────────────────────────────────────────────
    cap.go(tom, '/scorecards/')
    cap.shot(tom, 'metrics-board-list', 'The Metrics Boards list for the Operations team', CONTENT)
    tom.get_by_role('link', name='Harbour operations').first.click()
    cap.shot(tom, 'metrics-board', 'A Metrics Board before this week is entered', CONTENT)
    tom.get_by_role('link', name='Enter this week').first.click()
    for field, value in zip(tom.locator('input[name^=value_]').all(), ('74', '13', '9900', '11', '98', '1')):
        field.fill(value)
    tom.locator('input[name^=notes_]').nth(3).fill('Crane out of service for two days.')
    cap.shot(tom, 'metrics-enter', 'The Enter Values page with this week filled in', CONTENT)
    tom.get_by_role('button', name='Save values').click()
    cap.shot(tom, 'metrics-saved', 'The Metrics Board with this week entered and the confirmation message', CONTENT)

    # ── Weekly Meeting (Priyanka runs it, Tom takes part) ────────────────────
    cap.go(priyanka, '/meetings/create/')
    priyanka.select_option('[name=team]', label='Operations')
    priyanka.fill('[name=scheduled_date]', (today + timedelta(days=7)).isoformat())
    cap.shot(priyanka, 'meeting-schedule-form', 'The Schedule Weekly Meeting form', 'main .card', 'main h1')
    priyanka.get_by_role('button', name='Schedule Weekly Meeting').click()
    cap.go(priyanka, '/meetings/')
    cap.shot(priyanka, 'meeting-list', 'The Weekly Meetings list: one scheduled, one for today, one complete', CONTENT)
    priyanka.locator('tr', has_text=today.strftime('%b')).filter(has_text=f'{today.day}, ').get_by_role('link').first.click()
    cap.shot(priyanka, 'meeting-ready', 'A scheduled Weekly Meeting with the agenda and the start button', CONTENT)
    priyanka.get_by_role('button', name='Start Weekly Meeting').first.click()
    meeting_path = priyanka.url.replace(cap.base_url, '')
    priyanka.fill('[name=personal_best]', 'Swam across the bay on Sunday.')
    priyanka.fill('[name=business_best]', 'The drill cards are back from the printer.')
    priyanka.locator('form[action$="/segue/"] button').click()

    cap.go(tom, meeting_path)
    tom.fill('[name=personal_best]', 'My son scored his first goal.')
    tom.fill('[name=business_best]', 'Saturday wait at the fuel dock was 13 minutes.')
    cap.shot(tom, 'meeting-check-in', 'The Check-in segment with one person\'s entry typed', CONTENT)
    tom.locator('form[action$="/segue/"] button').click()

    def next_segment():
        priyanka.locator('form[action$="/advance/"] button').click()

    next_segment()
    cap.shot(priyanka, 'meeting-metrics-review', 'The Metrics Board Review segment', CONTENT)
    next_segment()
    cap.shot(priyanka, 'meeting-priority-review', 'The Priority Review segment', CONTENT)
    next_segment()
    priyanka.fill('[name=text]', 'Second card reader is fitted and working.')
    priyanka.locator('form[action$="/headlines/add/"] button').click()
    cap.go(tom, meeting_path)
    tom.select_option('[name=headline_type]', index=1)
    tom.fill('[name=text]', 'The slipway gate was left open twice last week.')
    tom.locator('form[action$="/headlines/add/"] button').click()
    cap.go(priyanka, meeting_path)
    cap.shot(priyanka, 'meeting-updates', 'The Updates segment with one piece of good news and one concern', CONTENT)
    next_segment()
    cap.shot(priyanka, 'meeting-action-review', 'The Action Review segment', CONTENT)
    next_segment()
    priyanka.locator('a[title^="Create Action"]').first.click()
    priyanka.fill('[name=title]', 'Phone the inspector\'s office on Monday')
    priyanka.select_option('[name=owner]', label='bo')
    priyanka.get_by_role('button', name='Create Action').click()
    priyanka.fill('[name=notes]', 'Crane: Bo phones the inspector on Monday. Crew cover: carry over to next week.')
    priyanka.get_by_role('button', name='Save Notes').click()
    cap.shot(priyanka, 'meeting-psr', 'The PSR segment: the list of open Blockers and the notes box',
             priyanka.locator('main .list-group').first, priyanka.locator('main .card').last)
    next_segment()
    cap.go(tom, meeting_path)
    tom.fill('[name=score]', '8')
    tom.fill('[name=improvement_note]', 'Start on time.')
    tom.get_by_role('button', name='Submit Rating').click()
    cap.go(priyanka, meeting_path)
    priyanka.fill('[name=score]', '9')
    priyanka.get_by_role('button', name='Submit Rating').click()
    priyanka.fill('[name=cascading_messages]', 'The second card reader is working. Fuel dock queues now form along the east wall.')
    cap.shot(priyanka, 'meeting-conclude', 'The Conclude segment: ratings, Actions created and Key Messages', CONTENT)
    priyanka.once('dialog', lambda dialog: dialog.accept())
    priyanka.get_by_role('button', name='Complete Weekly Meeting').click()
    cap.shot(priyanka, 'meeting-complete', 'A completed Weekly Meeting: ratings, notes, Key Messages and Actions', CONTENT)

    # ── People and teams (Ada Marsh, an Admin) ───────────────────────────────
    ada = cap.sign_in('ada')
    ada.click('button[type=submit]')
    ada.locator('nav .nav-link', has=ada.locator('.bi-person-circle')).click()
    cap.shot(ada, 'user-menu', 'The user menu in the navigation bar, open, for an Admin',
             ada.locator('nav .nav-link', has=ada.locator('.bi-person-circle')),
             ada.locator('.dropdown-menu.show'))
    ada.keyboard.press('Escape')
    cap.go(ada, '/users/')
    cap.shot(ada, 'users-list', 'The Users page listing everyone in the organisation', CONTENT)
    ada.get_by_role('link', name='Invite user').first.click()
    ada.fill('[name=first_name]', 'Mina')
    ada.fill('[name=last_name]', 'Castell')
    ada.fill('[name=username]', 'mina')
    ada.fill('[name=email]', 'mina.castell@example.com')
    ada.select_option('[name=role]', label='Team Member')
    cap.shot(ada, 'invite-form', 'The Invite a user form, filled in', 'main .card', 'main h1')
    ada.get_by_role('button', name='Create user').click()
    cap.shot(ada, 'invite-done', 'The Users page after an invitation, with the confirmation message', CONTENT)
    cap.go(ada, '/teams/')
    cap.shot(ada, 'team-list', 'The Teams page', CONTENT)
    ada.locator('.card', has_text='Operations').get_by_role('link', name='View').click()
    members = ada.locator('main .card', has_text='Update members').last
    members.locator('label', has_text='mina').click()
    cap.shot(ada, 'team-members', 'A team page: the members, and the Update members tick boxes with one more person ticked', members)
    members.get_by_role('button', name='Save members').click()

    # ── Export ───────────────────────────────────────────────────────────────
    cap.go(ada, '/org/')
    cap.shot(ada, 'organisation-page', 'The Organisation page for an Admin', CONTENT)
    cap.go(ada, '/org/export/')
    ada.fill('[name=password]', PASSWORD)
    cap.shot(ada, 'export-confirm', 'The Export data page: the password box and the download button',
             ada.locator('main form'))
    with ada.expect_download() as download:
        ada.get_by_role('button', name='Download archive').click()
    print('Downloaded', download.value.suggested_filename)
    cap.go(ada, '/org/audit/')
    cap.shot(ada, 'audit-log', 'The Audit log showing the export and the sign-ins', CONTENT)

    # ── Terminology (changed, captured, then reset) ──────────────────────────
    cap.go(ada, '/org/settings/terminology/')
    ada.fill('[name=issue]', 'Obstacle')
    ada.fill('[name=issues]', 'Obstacles')
    cap.shot(ada, 'terminology-form', 'The Terminology page with Blocker renamed to Obstacle', CONTENT)
    ada.get_by_role('button', name='Save terminology').click()
    cap.shot(ada, 'terminology-renamed', 'The navigation bar after renaming Blocker to Obstacle', 'nav.navbar', '.alert')
    ada.once('dialog', lambda dialog: dialog.accept())
    ada.get_by_role('button', name='Reset to defaults').click()

    # ── Name, logo and colours (changed, captured, then put back) ────────────
    cap.go(ada, '/org/settings/')
    ada.fill('[name=tagline]', 'Safe harbour, warm welcome')
    ada.fill('[name=primary_color]', '#0b6e6e')
    ada.select_option('[name=navbar_style]', label='Primary colour')
    cap.shot(ada, 'organisation-settings', 'The Organisation settings page with a tagline and a colour chosen', CONTENT)
    ada.get_by_role('button', name='Save settings').click()
    cap.shot(ada, 'organisation-settings-saved', 'The Organisation page in the new colour, with the tagline in the footer',
             'nav.navbar', CONTENT, 'footer', pad=0)
    cap.go(ada, '/org/settings/')
    ada.fill('[name=tagline]', '')
    ada.fill('[name=primary_color]', '#0d6efd')
    ada.select_option('[name=navbar_style]', label='Dark')
    ada.get_by_role('button', name='Save settings').click()

    # ── Two-step sign-in (Christopher Okafor) ────────────────────────────────
    chris = cap.sign_in('christopher')
    chris.click('button[type=submit]')
    cap.go(chris, '/profile/')
    cap.shot(chris, 'profile-two-factor', 'My Profile with two-factor authentication not yet enabled', CONTENT)
    chris.get_by_role('link', name='Set up two-factor authentication').click()
    key = chris.locator('main code').first.inner_text()
    cap.shot(chris, 'two-factor-setup', 'The set-up page: a QR code, the key and the box for the 6-digit code', CONTENT)
    chris.fill('[name=token]', totp(key))
    chris.get_by_role('button', name='Enable two-factor authentication').click()
    cap.shot(chris, 'two-factor-backup-codes', 'The ten backup codes shown once after set-up', CONTENT)
    cap.go(chris, '/profile/')
    cap.shot(chris, 'profile-two-factor-enabled', 'My Profile with two-factor authentication enabled',
             card(chris, 'Two-factor authentication'))
    chris.context.clear_cookies()
    wait_for_next_code()
    chris.goto(cap.base_url + '/accounts/login/')
    chris.fill('#id_username', 'christopher')
    chris.fill('#id_password', PASSWORD)
    chris.click('button[type=submit]')
    chris.fill('[name=token]', totp(key))
    cap.shot(chris, 'two-factor-verify', 'The second step at sign-in asking for a 6-digit code', '.card', 'h1', pad=24)
    chris.get_by_role('button', name='Continue').click()
    chris.wait_for_url(cap.base_url + '/')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--base-url', default='http://localhost:8040')
    parser.add_argument('--out', default=str(Path(__file__).resolve().parent.parent / '_static' / 'screenshots'))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        cap = Capture(browser, args.base_url, out_dir)
        try:
            run(cap)
        except Exception:
            # Leave a picture of where each signed-in person was when it failed.
            debug_dir = out_dir.parent.parent / '_build'
            debug_dir.mkdir(exist_ok=True)
            for number, context in enumerate(browser.contexts):
                for page in context.pages:
                    page.screenshot(path=str(debug_dir / f'capture-failed-{number}.png'), full_page=True)
            raise
        finally:
            manifest = Path(__file__).resolve().parent / 'screenshots.json'
            manifest.write_text(json.dumps(cap.manifest, indent=2) + '\n', encoding='utf-8')
            browser.close()
    total = sum(p.stat().st_size for p in out_dir.glob('*.png'))
    print(f'{len(cap.manifest)} screenshots, {total // 1024} KB in total.')


if __name__ == '__main__':
    main()
