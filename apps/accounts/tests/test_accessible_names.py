"""Every control on the main pages has a name a screen reader can announce.

The browser check in ``accessibility/`` finds these too, but it is opt-in and
needs Chromium. These tests read the HTML the views return, so the default
suite catches an icon-only button or an unlabelled field as soon as it is added.
"""
import unittest
from html.parser import HTMLParser

from django.test import TestCase

from apps.accounts.models import Organization
from apps.meetings.models import Meeting

try:
    from accessibility import seed
except ImportError:  # .dockerignore keeps the accessibility package out of the production image
    seed = None

UNNAMED_INPUT_TYPES = {'hidden', 'submit', 'button', 'reset', 'image'}


class ControlNames(HTMLParser):
    """Collects links, buttons and form fields that have no accessible name.

    A name is text inside the element, an ``aria-label`` or ``title``, an
    image's ``alt``, or for a field a ``<label>`` that wraps it or points at
    its ``id``. A placeholder is not counted: it disappears on typing.
    """

    def __init__(self):
        super().__init__()
        self.open_controls = []   # [tag, attrs, has_name] for each open <a> or <button>
        self.label_depth = 0
        self.label_targets = set()
        self.fields = []          # (description, id, labelled already)
        self.unnamed = []

    @staticmethod
    def describe(tag, attrs):
        shown = ' '.join(f'{key}="{attrs[key]}"' for key in ('href', 'name', 'class') if attrs.get(key))
        return f'<{tag} {shown}>'

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or '' for key, value in attrs}
        named = bool(attrs.get('aria-label', '').strip() or attrs.get('title', '').strip())
        if tag in ('a', 'button'):
            if tag == 'a' and 'href' not in attrs:
                return
            self.open_controls.append([tag, attrs, named])
        elif tag == 'label':
            self.label_depth += 1
            if attrs.get('for'):
                self.label_targets.add(attrs['for'])
        elif tag == 'img' and attrs.get('alt', '').strip():
            for control in self.open_controls:
                control[2] = True
        elif tag in ('input', 'select', 'textarea'):
            if tag == 'input' and attrs.get('type', 'text') in UNNAMED_INPUT_TYPES:
                return
            named = named or bool(attrs.get('aria-labelledby')) or self.label_depth > 0
            self.fields.append((self.describe(tag, attrs), attrs.get('id', ''), named))

    def handle_data(self, data):
        if data.strip():
            for control in self.open_controls:
                control[2] = True

    def handle_endtag(self, tag):
        if tag == 'label':
            self.label_depth = max(0, self.label_depth - 1)
        elif tag in ('a', 'button') and self.open_controls and self.open_controls[-1][0] == tag:
            tag, attrs, named = self.open_controls.pop()
            if not named:
                self.unnamed.append(self.describe(tag, attrs))

    def close(self):
        super().close()
        for description, field_id, named in self.fields:
            if not named and not (field_id and field_id in self.label_targets):
                self.unnamed.append(description)


@unittest.skipIf(seed is None, 'Needs the demo organisation in accessibility/seed.py, which this image leaves out')
class AccessibleNameTest(TestCase):
    def setUp(self):
        self.ids = seed.seed()
        self.assertTrue(self.client.login(username=seed.USERNAME, password=seed.PASSWORD))

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response

    def pages(self):
        ids = self.ids
        # Left out: the new Priority and new Action forms, whose Team select
        # has no name until the Team picker fix (#114) is merged, and the
        # Metrics Board entry form, whose fields get their labels in #129.
        return [
            '/',
            '/rocks/',
            f'/rocks/{ids["rock"]}/',
            '/rocks/archive/',
            f'/rocks/milestones/{ids["milestone"]}/edit/',
            '/issues/',
            f'/issues/{ids["issue"]}/',
            '/todos/',
            '/todos/?view=team',
            '/scorecards/',
            f'/scorecards/{ids["scorecard"]}/',
            '/meetings/',
            f'/meetings/{ids["past_meeting"]}/',
            '/vision/',
            '/accountability/',
            '/search/?q=depot',
        ]

    def assert_all_named(self, path):
        parser = ControlNames()
        parser.feed(self.get(path).content.decode())
        parser.close()
        self.assertEqual(parser.unnamed, [], f'{path} has controls with no accessible name')

    def test_every_link_button_and_field_has_a_name(self):
        for path in self.pages():
            with self.subTest(path=path):
                self.assert_all_named(path)

    def test_every_meeting_segment_has_named_controls(self):
        meeting = Meeting.objects.get(pk=self.ids['meeting'])
        for position, entry in enumerate(meeting.agenda):
            with self.subTest(segment=entry['segment_type']):
                Meeting.objects.filter(pk=meeting.pk).update(current_segment=position)
                self.assert_all_named(meeting.get_absolute_url())

    def test_names_say_which_record_they_act_on(self):
        ids = self.ids
        for path, labels in [
            ('/rocks/', [
                'aria-label="Previous quarter"',
                'aria-label="Next quarter"',
                'aria-label="Options for Open the Plymouth depot"',
            ]),
            (f'/rocks/{ids["rock"]}/', [
                'aria-label="Back to Priorities"',
                'aria-label="Options for Open the Plymouth depot"',
                'aria-label="Add Action for Open the Plymouth depot"',
                'aria-label="Steps completed"',
                'aria-label="Step due date"',
                'aria-label="Priority this one depends on"',
                'aria-label="Blocker to link"',
            ]),
            (f'/issues/{ids["issue"]}/', [
                'aria-label="Back to Blockers"',
                'aria-label="Options for Engineers double-booked on Fridays"',
                'aria-label="Add Action for Engineers double-booked on Fridays"',
                'aria-label="Delegate to team"',
            ]),
            ('/todos/', ['aria-label="Options for Send the fit-out quotes to finance"']),
            (f'/scorecards/{ids["scorecard"]}/', [
                'aria-label="Back to Metrics Boards"',
                'aria-label="Options for Leadership weekly numbers"',
                'aria-label="Options for Quotes sent"',
            ]),
            (f'/scorecards/{ids["scorecard"]}/enter/', [
                'aria-label="Back to Leadership weekly numbers"',
            ]),
            ('/vision/', [
                'aria-label="Add Value"',
                'aria-label="Edit Value Do it properly"',
                'aria-label="Delete Value Do it properly"',
                'aria-label="Edit Purpose',
                'aria-label="Open Priorities"',
                'aria-label="New Blocker"',
            ]),
            ('/accountability/', [
                'aria-label="Edit accountability Sets direction"',
                'aria-label="Delete accountability Sets direction"',
            ]),
        ]:
            html = self.get(path).content.decode()
            for label in labels:
                with self.subTest(path=path, label=label):
                    self.assertIn(label, html)

    def test_names_use_the_organisations_own_words(self):
        Organization.objects.update(terminology={
            'rock': 'Objective', 'rocks': 'Objectives',
            'todo': 'Task', 'todos': 'Tasks',
            'milestone': 'Checkpoint', 'milestones': 'Checkpoints',
        })
        html = self.get(f'/rocks/{self.ids["rock"]}/').content.decode()
        for label in [
            'aria-label="Back to Objectives"',
            'aria-label="Add Task for Open the Plymouth depot"',
            'aria-label="Checkpoints completed"',
            'aria-label="Objective this one depends on"',
        ]:
            with self.subTest(label=label):
                self.assertIn(label, html)
        self.assertNotIn('aria-label="Back to Priorities"', html)

    def test_small_icon_links_get_the_larger_target(self):
        for path, count in [('/vision/', 4), ('/accountability/', 6)]:
            with self.subTest(path=path):
                self.assertContains(self.get(path), 'icon-target', count=count)

    def test_help_text_is_wired_to_its_field(self):
        html = self.get('/org/settings/').content.decode()
        self.assertIn('aria-describedby="id_tagline_helptext"', html)
        self.assertIn('id="id_tagline_helptext"', html)

    def test_dashboard_counts_avoid_the_low_contrast_colours(self):
        html = self.get('/').content.decode()
        self.assertIn('fs-4 fw-bold text-info-emphasis', html)
        self.assertNotIn('fw-bold text-info"', html)
