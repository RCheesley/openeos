"""Keyboard focus order on the forms people use most.

axe-core does not follow the Tab key, and a wrong tab order on the sign-in
form (#6) is what prompted this check, so these tests press Tab and look at
where the focus lands.
"""
from .base import BrowserTestCase

# What the focused element is, in words a failure message can use.
DESCRIBE_FOCUS = '''() => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const box = el.getBoundingClientRect();
    const sameAsLast = el === window.__lastFocused;
    window.__lastFocused = el;
    return {
        sameAsLast,
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        id: el.id,
        name: el.getAttribute('name') || '',
        text: (el.innerText || el.value || '').trim().slice(0, 40),
        inForm: !!el.closest('main form, .card form'),
        top: Math.round(box.top + window.scrollY),
        left: Math.round(box.left),
        tabindex: el.tabIndex,
    };
}'''

FIELD_TAGS = {'input', 'select', 'textarea'}
# Controls of different heights on one row do not share an exact top edge.
SAME_ROW_PX = 24


class SignInFocusOrderTest(BrowserTestCase):
    def test_tab_goes_username_password_forgot_link_then_sign_in(self):
        self.open('/accounts/login/')
        stops = [self.page.evaluate(DESCRIBE_FOCUS)]
        for _ in range(3):
            self.page.keyboard.press('Tab')
            stops.append(self.page.evaluate(DESCRIBE_FOCUS))

        self.assertIsNotNone(stops[0], 'Nothing has focus when the sign-in page opens')
        self.assertEqual(
            [stop and (stop['id'] or stop['text']) for stop in stops],
            ['id_username', 'id_password', 'Forgot password?', 'Sign in'],
        )

    def test_shift_tab_walks_back_the_same_way(self):
        self.open('/accounts/login/')
        self.page.focus('button[type=submit]')
        stops = []
        for _ in range(3):
            self.page.keyboard.press('Shift+Tab')
            stops.append(self.page.evaluate(DESCRIBE_FOCUS))
        self.assertEqual(
            [stop and (stop['id'] or stop['text']) for stop in stops],
            ['Forgot password?', 'id_password', 'id_username'],
        )


class MainFormFocusOrderTest(BrowserTestCase):
    """Tab moves through a form's fields without a detour, then reaches its button.

    The rule is written against the shape of the form, not a list of field
    names, so adding a field does not break it but putting a link or button
    between two fields does.
    """

    def assert_fields_then_submit(self, path, first_field):
        self.sign_in()
        self.open(path)
        self.page.focus(first_field)
        stops = [self.page.evaluate(DESCRIBE_FOCUS)]
        for _ in range(60):
            if stops[-1] is None or stops[-1]['type'] == 'submit':
                break
            self.page.keyboard.press('Tab')
            stop = self.page.evaluate(DESCRIBE_FOCUS)
            # A date input is one element with several Tab stops inside it
            # (day, month, year, picker); count it once.
            if stop is None or not stop['sameAsLast']:
                stops.append(stop)

        trail = ' > '.join(
            'nothing' if stop is None else (stop['id'] or stop['name'] or stop['text'] or stop['tag'])
            for stop in stops
        )
        last = stops[-1]
        self.assertIsNotNone(last, f'{path}: focus left the page before reaching the submit button: {trail}')
        self.assertEqual(last['type'], 'submit', f'{path}: Tab never reached the submit button: {trail}')
        self.assertTrue(last['inForm'], f'{path}: the first submit button reached is outside the form: {trail}')
        self.assertGreater(len(stops), 3, f'{path}: expected several fields before the submit button: {trail}')

        previous = None
        for stop in stops[:-1]:
            self.assertIn(
                stop['tag'], FIELD_TAGS,
                f'{path}: Tab stops on "{stop["text"] or stop["tag"]}" between the fields: {trail}',
            )
            self.assertEqual(stop['tabindex'], 0, f'{path}: {stop["id"]} has a tabindex that reorders focus')
            if previous is not None:
                same_row = abs(stop['top'] - previous['top']) <= SAME_ROW_PX
                moves_on = stop['left'] > previous['left'] if same_row else stop['top'] > previous['top']
                self.assertTrue(
                    moves_on,
                    f'{path}: focus jumps backwards on screen from {previous["id"]} to {stop["id"]}: {trail}',
                )
            previous = stop

    def test_priority_form(self):
        self.assert_fields_then_submit('/rocks/new/', '#id_title')

    def test_action_form(self):
        self.assert_fields_then_submit('/todos/new/', '#id_title')
