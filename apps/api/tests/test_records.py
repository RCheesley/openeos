"""Metrics boards, meetings, the vision document and the org chart: what each returns, and to whom."""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accountability.models import AccountabilityNode, AccountabilityRole
from apps.accounts.models import Membership, Team
from apps.accounts.team_scope import SCOPE_ALL
from apps.api.terminology import SEGMENT_TYPE_TO_API
from apps.meetings import segments
from apps.meetings.models import Headline, Meeting, MeetingNote, MeetingRating, MeetingSegmentDefinition
from apps.scorecards.models import Scorecard, ScorecardEntry, ScorecardMetric
from apps.vision.models import VTO, VisionPage, VisionSectionDefinition, VisionSectionGroup, VTOSection

from .helpers import ApiTestCase, issue_token


class TwoTeamsTestCase(ApiTestCase):
    """One organisation, two teams. Mo is a member of Alpha only; the admin sees both."""

    def setUp(self):
        super().setUp()
        self.admin = self.user
        self.alpha = self.mine['team']
        self.beta = Team.objects.create(organization=self.org, name='Beta')
        self.mo = User.objects.create_user('mo', password='pw', first_name='Mo', last_name='Member')
        Membership.objects.create(user=self.mo, organization=self.org, role=Membership.ROLE_MEMBER)
        self.mo.profile.teams.add(self.alpha)
        self.mo_token = issue_token(self.mo, self.org)

    def ids(self, path, token=None):
        return [row['id'] for row in self.results(path, token)]

    def count_queries(self, path):
        self.api_get(path)  # the first use of a token costs a query of its own
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.api_get(path).status_code, 200)
        return len(captured)

    def walk(self, path):
        """Follow ``next`` links to the end; return the pages of ids."""
        pages, url = [], f'/api/v1/{path}'
        while url:
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {self.token}')
            self.assertEqual(response.status_code, 200, response.content)
            body = response.json()
            self.assertEqual(set(body), {'next', 'previous', 'results'})
            pages.append([row['id'] for row in body['results']])
            url = body['next']
        return pages


class MetricsBoardTest(TwoTeamsTestCase):
    def setUp(self):
        super().setUp()
        self.board = self.mine['scorecard']
        self.metric = self.mine['metric']
        self.beta_board = Scorecard.objects.create(name='Beta board', team=self.beta)
        self.retired = Scorecard.objects.create(name='Retired board', team=self.alpha, is_active=False)

    def test_member_lists_only_their_teams_boards(self):
        self.assertEqual(self.ids('metrics-boards', self.mo_token), [self.board.pk, self.retired.pk])

    def test_admin_lists_every_teams_boards(self):
        self.assertEqual(self.ids('metrics-boards'), [self.board.pk, self.beta_board.pk, self.retired.pk])

    def test_active_boards_match_the_web_list_for_the_same_user(self):
        for user, token in ((self.mo, self.mo_token), (self.admin, self.token)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                page = self.client.get('/scorecards/', {'scope': SCOPE_ALL})
                web_ids = {board.pk for board in page.context['scorecards']}
                self.client.logout()
                self.assertEqual(set(self.ids('metrics-boards?is_active=true', token)), web_ids)

    def test_member_cannot_widen_the_list_with_the_team_filter(self):
        self.assertEqual(self.ids(f'metrics-boards?team={self.beta.pk}', self.mo_token), [])
        self.assertEqual(self.ids(f'metrics-boards?team={self.beta.pk}'), [self.beta_board.pk])

    def test_by_id_follows_the_web_detail_page(self):
        """The web opens any board of the organisation by its address; so does the API."""
        self.client.force_login(self.mo)
        web = self.client.get(f'/scorecards/{self.beta_board.pk}/').status_code
        self.client.logout()
        api = self.api_get(f'metrics-boards/{self.beta_board.pk}', self.mo_token).status_code
        self.assertEqual((web, api), (200, 200))

    def test_filters(self):
        self.assertEqual(self.ids('metrics-boards?is_active=false'), [self.retired.pk])
        self.assertProblem(self.api_get('metrics-boards?is_active=yes'), 400)
        self.assertProblem(self.api_get('metrics-boards?team=alpha'), 400)

    def test_updated_since_returns_what_changed(self):
        cutoff = timezone.now()
        Scorecard.objects.update(updated_at=cutoff - timedelta(hours=1))
        Scorecard.objects.filter(pk=self.beta_board.pk).update(updated_at=cutoff + timedelta(seconds=5))
        stamp = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(self.ids(f'metrics-boards?updated_since={stamp}'), [self.beta_board.pk])

    def test_pages_cover_every_board_once_in_a_stable_order(self):
        boards = [self.board, self.beta_board, self.retired]
        pages = self.walk('metrics-boards?limit=2')
        self.assertEqual(pages, [[boards[0].pk, boards[1].pk], [boards[2].pk]])
        self.assertEqual(pages, self.walk('metrics-boards?limit=2'))
        self.assertEqual(sum(self.walk('metrics-boards?limit=2&ordering=-id'), []), [b.pk for b in reversed(boards)])
        self.assertProblem(self.api_get('metrics-boards?ordering=name'), 400)

    def test_board_uses_generic_names(self):
        body = self.api_get(f'metrics-boards/{self.board.pk}').json()
        self.assertEqual(
            set(body), {'id', 'name', 'description', 'team_id', 'is_active', 'created_at', 'updated_at'},
        )
        self.assertEqual((body['name'], body['team_id'], body['is_active']), ('Mine Scorecard', self.alpha.pk, True))

    def test_metrics_are_listed_in_board_order(self):
        last = ScorecardMetric.objects.create(
            scorecard=self.board, name='Zeta', owner=self.user, goal_value=3, order=2,
            metric_type='percentage', goal_direction='below', frequency='monthly',
        )
        first = ScorecardMetric.objects.create(
            scorecard=self.board, name='Old', owner=self.mo, goal_value=1, order=0, is_active=False,
        )
        ScorecardMetric.objects.filter(pk=self.metric.pk).update(order=1)
        path = f'metrics-boards/{self.board.pk}/metrics'
        self.assertEqual(self.ids(path), [first.pk, self.metric.pk, last.pk])
        self.assertEqual(self.ids(f'{path}?is_active=true'), [self.metric.pk, last.pk])
        self.assertEqual(self.walk(f'{path}?limit=2'), [[first.pk, self.metric.pk], [last.pk]])
        self.assertEqual(self.ids(f'{path}?ordering=-id'), [first.pk, last.pk, self.metric.pk])
        body = self.results(path)[2]
        self.assertEqual(body, {
            'id': last.pk, 'metrics_board_id': self.board.pk, 'name': 'Zeta',
            'owner': {'id': self.user.pk, 'name': self.user.username},
            'type': 'percentage', 'goal_value': '3.0000', 'goal_direction': 'below',
            'frequency': 'monthly', 'order': 2, 'is_active': True,
        })

    def test_entries_for_a_metric(self):
        entry = self.mine['entry']
        entry.notes = 'Slow week'
        entry.save()
        body = self.results(f'metrics-boards/{self.board.pk}/metrics/{self.metric.pk}/entries')[0]
        self.assertEqual(body['id'], entry.pk)
        self.assertEqual(body['metric_id'], self.metric.pk)
        self.assertEqual(body['period_start'], '2026-01-05')
        self.assertEqual(body['value'], '5.0000')
        self.assertIs(body['on_track'], False)  # the goal is 10 or more
        self.assertEqual(body['note'], 'Slow week')
        self.assertEqual(body['entered_by'], {'id': self.user.pk, 'name': self.user.username})
        self.assertTrue(body['created_at'].endswith('Z'))

    def test_entries_are_paged_newest_period_first_and_filtered_by_date(self):
        entries = [self.mine['entry']] + [
            ScorecardEntry.objects.create(
                metric=self.metric, period_start=date(2026, 1, 5) + timedelta(weeks=n), value=10 + n,
            )
            for n in range(1, 5)
        ]
        path = f'metrics-boards/{self.board.pk}/metrics/{self.metric.pk}/entries'
        newest_first = [entry.pk for entry in reversed(entries)]
        pages = self.walk(f'{path}?limit=2')
        self.assertEqual([len(page) for page in pages], [2, 2, 1])
        self.assertEqual(sum(pages, []), newest_first)
        self.assertEqual(pages, self.walk(f'{path}?limit=2'))
        self.assertEqual(sum(self.walk(f'{path}?limit=2&ordering=period_start'), []), newest_first[::-1])
        # Both ends of the range are included.
        self.assertEqual(
            self.ids(f'{path}?from=2026-01-12&to=2026-01-26'), [entries[3].pk, entries[2].pk, entries[1].pk],
        )
        self.assertEqual(self.ids(f'{path}?to=2026-01-05'), [entries[0].pk])
        self.assertEqual(self.ids(f'{path}?from=2026-02-02'), [entries[4].pk])
        for bad in ('from=January', 'to=2026-13-01'):
            with self.subTest(bad=bad):
                body = self.assertProblem(self.api_get(f'{path}?{bad}'), 400)
                self.assertIn(bad.split('=')[0], body['errors'])


class MeetingTest(TwoTeamsTestCase):
    def setUp(self):
        super().setUp()
        self.meeting = self.mine['meeting']  # Alpha, 5 January 2026, scheduled
        self.beta_meeting = Meeting.objects.create(team=self.beta, scheduled_date=date(2026, 1, 6))
        self.done = Meeting.objects.create(
            team=self.alpha, scheduled_date=date(2026, 1, 12), status=Meeting.STATUS_COMPLETE,
            started_at=timezone.now() - timedelta(minutes=90), ended_at=timezone.now(),
            cascading_messages='Tell everyone about the new rota.', created_by=self.user,
        )

    def test_member_lists_only_their_teams_meetings(self):
        self.assertEqual(self.ids('meetings', self.mo_token), [self.meeting.pk, self.done.pk])

    def test_admin_lists_every_teams_meetings(self):
        self.assertEqual(self.ids('meetings'), [self.meeting.pk, self.beta_meeting.pk, self.done.pk])

    def test_a_members_list_holds_what_the_web_lists_for_each_of_their_teams(self):
        self.mo.profile.teams.add(self.beta)
        web_ids = set()
        self.client.force_login(self.mo)
        for team in (self.alpha, self.beta):
            session = self.client.session
            session['active_team_id'] = team.pk
            session.save()
            web_ids |= {meeting.pk for meeting in self.client.get('/meetings/').context['meetings']}
        self.client.logout()
        self.assertEqual(set(self.ids('meetings', self.mo_token)), web_ids)

    def test_member_cannot_widen_the_list_with_the_team_filter(self):
        self.assertEqual(self.ids(f'meetings?team={self.beta.pk}', self.mo_token), [])
        self.assertEqual(self.ids(f'meetings?team={self.beta.pk}'), [self.beta_meeting.pk])

    def test_by_id_follows_the_web_detail_page(self):
        self.client.force_login(self.mo)
        web = self.client.get(f'/meetings/{self.beta_meeting.pk}/').status_code
        self.client.logout()
        api = self.api_get(f'meetings/{self.beta_meeting.pk}', self.mo_token).status_code
        self.assertEqual((web, api), (200, 200))

    def test_filters(self):
        self.assertEqual(self.ids('meetings?status=complete'), [self.done.pk])
        self.assertEqual(self.ids('meetings?from=2026-01-06'), [self.beta_meeting.pk, self.done.pk])
        self.assertEqual(self.ids('meetings?to=2026-01-06'), [self.meeting.pk, self.beta_meeting.pk])
        self.assertEqual(self.ids('meetings?from=2026-01-06&to=2026-01-06'), [self.beta_meeting.pk])
        for bad in ('status=finished', 'from=soon', 'to=2026-02-30', 'team=alpha'):
            with self.subTest(bad=bad):
                body = self.assertProblem(self.api_get(f'meetings?{bad}'), 400)
                self.assertIn(bad.split('=')[0], body['errors'])

    def test_pages_cover_every_meeting_once_in_a_stable_order(self):
        in_id_order = [self.meeting.pk, self.beta_meeting.pk, self.done.pk]
        pages = self.walk('meetings?limit=2')
        self.assertEqual(pages, [in_id_order[:2], in_id_order[2:]])
        self.assertEqual(pages, self.walk('meetings?limit=2'))
        # Two meetings on one date keep a fixed order: the id breaks the tie.
        twin = Meeting.objects.create(team=self.beta, scheduled_date=date(2026, 1, 12))
        newest_first = [twin.pk, self.done.pk, self.beta_meeting.pk, self.meeting.pk]
        self.assertEqual(sum(self.walk('meetings?limit=1&ordering=-scheduled_date'), []), newest_first)
        self.assertEqual(sum(self.walk('meetings?limit=3&ordering=scheduled_date'), []), newest_first[::-1])
        self.assertProblem(self.api_get('meetings?ordering=updated_at'), 400)

    def test_default_agenda_under_generic_names(self):
        body = self.api_get(f'meetings/{self.meeting.pk}').json()
        self.assertEqual(
            [(item['position'], item['type'], item['name'], item['duration_minutes']) for item in body['agenda']],
            [
                (0, 'meeting_opener', 'Check-in', 5), (1, 'metrics_board_review', 'Metrics Board Review', 5),
                (2, 'priority_review', 'Priority Review', 5), (3, 'updates', 'Updates', 5),
                (4, 'action_review', 'Action Review', 5), (5, 'problem_solving', 'PRS', 60),
                (6, 'conclude', 'Conclude', 5),
            ],
        )
        self.assertEqual((body['status'], body['current_position']), ('scheduled', 0))
        self.assertEqual((body['team_id'], body['scheduled_date']), (self.alpha.pk, '2026-01-05'))
        self.assertIsNone(body['duration_minutes'])
        self.assertIsNone(body['average_rating'])
        self.assertEqual((body['notes'], body['updates'], body['ratings'], body['key_messages']), ([], [], [], ''))

    def test_agenda_is_the_one_frozen_on_the_meeting(self):
        MeetingSegmentDefinition.objects.create(
            organization=self.org, order=0, segment_type=segments.CUSTOM_NOTES, label='Wins', duration_minutes=10,
        )
        MeetingSegmentDefinition.objects.create(
            organization=self.org, order=1, segment_type=segments.IDS, duration_minutes=45,
        )
        custom = Meeting.objects.create(team=self.alpha, scheduled_date=date(2026, 2, 2))
        self.org.terminology = {'ids': 'Solve it'}
        self.org.save()
        agenda = self.api_get(f'meetings/{custom.pk}').json()['agenda']
        self.assertEqual(
            [(item['type'], item['name'], item['duration_minutes']) for item in agenda],
            [('custom', 'Wins', 10), ('problem_solving', 'Solve it', 45), ('conclude', 'Conclude', 5)],
        )
        # The earlier meeting keeps the agenda it was created with.
        self.assertEqual(len(self.api_get(f'meetings/{self.meeting.pk}').json()['agenda']), 7)

    def test_every_kind_of_agenda_item_has_a_fixed_api_name(self):
        stored = {value for value, _ in segments.SEGMENT_TYPE_CHOICES} | {segments.CONCLUDE}
        self.assertEqual(set(SEGMENT_TYPE_TO_API), stored)
        self.assertEqual(len(set(SEGMENT_TYPE_TO_API.values())), len(SEGMENT_TYPE_TO_API))

    def test_what_a_finished_meeting_recorded(self):
        MeetingNote.objects.create(meeting=self.done, segment=5, text='Agreed the rota.', updated_by=self.mo)
        MeetingNote.objects.create(meeting=self.done, segment=1, text='Sales dipped.', updated_by=None)
        good = Headline.objects.create(meeting=self.done, author=self.mo, text='New client signed')
        Headline.objects.create(
            meeting=self.done, author=self.user, headline_type=Headline.TYPE_BAD, text='Supplier late',
            escalated_issue=self.mine['issue'],
        )
        MeetingRating.objects.create(meeting=self.done, participant=self.user, score=8, improvement_note='Start on time')
        MeetingRating.objects.create(meeting=self.done, participant=self.mo, score=9)
        MeetingRating.objects.create(meeting=self.meeting, participant=self.mo, score=1)  # another meeting's

        body = self.api_get(f'meetings/{self.done.pk}').json()
        self.assertEqual(body['status'], 'complete')
        self.assertEqual(body['duration_minutes'], 90)
        self.assertEqual(body['key_messages'], 'Tell everyone about the new rota.')
        self.assertEqual(body['created_by']['id'], self.user.pk)
        self.assertEqual(
            [(note['position'], note['text'], note['updated_by']) for note in body['notes']],
            [(1, 'Sales dipped.', None), (5, 'Agreed the rota.', {'id': self.mo.pk, 'name': 'Mo Member'})],
        )
        self.assertEqual(
            [(u['type'], u['text'], u['author']['id'], u['blocker_id']) for u in body['updates']],
            [('good', 'New client signed', self.mo.pk, None), ('bad', 'Supplier late', self.user.pk, self.mine['issue'].pk)],
        )
        self.assertEqual(body['updates'][0]['id'], good.pk)
        self.assertEqual(
            sorted((r['participant']['id'], r['score'], r['note']) for r in body['ratings']),
            sorted([(self.user.pk, 8, 'Start on time'), (self.mo.pk, 9, '')]),
        )
        self.assertEqual(body['average_rating'], 8.5)
        self.assertEqual(body['average_rating'], self.done.average_rating)
        self.assertFalse({'segment', 'current_segment', 'cascading_messages', 'headlines'} & set(body))

    def test_list_rows_are_the_same_as_the_record_by_id(self):
        MeetingRating.objects.create(meeting=self.done, participant=self.user, score=7)
        row = next(row for row in self.results('meetings') if row['id'] == self.done.pk)
        self.assertEqual(row, self.api_get(f'meetings/{self.done.pk}').json())

    def test_listing_does_not_query_once_per_meeting(self):
        def record(meeting):
            MeetingNote.objects.create(meeting=meeting, segment=0, text='Noted', updated_by=self.mo)
            Headline.objects.create(meeting=meeting, author=self.mo, text='News')
            MeetingRating.objects.create(meeting=meeting, participant=self.mo, score=6)

        record(self.done)
        before = self.count_queries('meetings')
        for day in (2, 3, 4):
            record(Meeting.objects.create(team=self.alpha, scheduled_date=date(2026, 3, day)))
        self.assertEqual(self.count_queries('meetings'), before)


class VisionBoardTest(TwoTeamsTestCase):
    def setUp(self):
        super().setUp()
        self.board = VTO.for_org(self.org)

    def sections(self, body):
        return {
            section['key']: section
            for page in body['pages'] for group in page['groups'] for section in group['sections']
        }

    def test_default_layout_with_stored_content(self):
        VTOSection.objects.create(vto=self.board, key='target_market').save_content('Harbour cafes', self.mo)
        body = self.api_get('vision-board').json()
        self.assertEqual(set(body), {'values', 'pages'})
        self.assertEqual([page['label'] for page in body['pages']], ['Vision', 'Delivery'])
        self.assertEqual(set(body['pages'][0]['groups'][0]), {'label', 'hint', 'sections'})
        sections = self.sections(body)
        written = sections['target_market']
        self.assertEqual(written['content'], 'Harbour cafes')
        self.assertEqual(written['last_edited_by'], {'id': self.mo.pk, 'name': 'Mo Member'})
        self.assertTrue(written['last_edited_at'].endswith('Z'))
        self.assertEqual(written['format'], 'text')
        unwritten = sections['one_year_goals']
        self.assertEqual(
            (unwritten['content'], unwritten['last_edited_by'], unwritten['last_edited_at'], unwritten['format']),
            ('', None, None, 'list'),
        )

    def test_values_in_their_order(self):
        self.board.core_values.create(name='Aim high', description='Every day', order=0)
        self.board.core_values.filter(name='Mine Value').update(order=1)
        values = self.api_get('vision-board').json()['values']
        self.assertEqual([value['name'] for value in values], ['Aim high', 'Mine Value'])
        self.assertEqual(set(values[0]), {'id', 'name', 'description', 'order'})

    def test_an_organisations_own_layout_is_returned(self):
        page = VisionPage.objects.create(organization=self.org, label='Plan')
        group = VisionSectionGroup.objects.create(page=page, label='This year', hint='Keep it short')
        VisionSectionDefinition.objects.create(group=group, key='theme', label='Theme', render_as='single_line')
        VTOSection.objects.create(vto=self.board, key='theme', content='Steady growth')
        VTOSection.objects.create(vto=self.board, key='target_market', content='No longer in the layout')
        body = self.api_get('vision-board').json()
        self.assertEqual(body['pages'], [{
            'label': 'Plan',
            'groups': [{
                'label': 'This year', 'hint': 'Keep it short',
                'sections': [{
                    'key': 'theme', 'label': 'Theme', 'format': 'single_line', 'content': 'Steady growth',
                    'last_edited_by': None, 'last_edited_at': None,
                }],
            }],
        }])

    def test_member_and_admin_see_the_same_document_as_on_the_web(self):
        self.assertEqual(self.api_get('vision-board', self.mo_token).json(), self.api_get('vision-board').json())
        self.client.force_login(self.mo)
        self.assertEqual(self.client.get('/vision/').status_code, 200)

    def test_reading_does_not_create_a_document(self):
        VTO.objects.filter(organization=self.org).delete()
        body = self.api_get('vision-board').json()
        self.assertEqual(body['values'], [])
        self.assertEqual(len(body['pages']), 2)
        self.assertFalse(VTO.objects.filter(organization=self.org).exists())


class OrgChartTest(TwoTeamsTestCase):
    def setUp(self):
        super().setUp()
        self.top = self.mine['node']
        self.top.owner = self.user
        self.top.save()
        self.sales = AccountabilityNode.objects.create(
            organization=self.org, parent=self.top, name='Sales', node_type='department', order=2,
        )
        self.ops = AccountabilityNode.objects.create(
            organization=self.org, parent=self.top, name='Operations lead', owner=self.mo, order=1,
        )
        self.rep = AccountabilityNode.objects.create(organization=self.org, parent=self.sales, name='Sales rep')
        AccountabilityRole.objects.create(node=self.ops, description='Rotas', order=2)
        AccountabilityRole.objects.create(node=self.ops, description='Budget', order=1)

    def test_chart_is_a_tree_in_chart_order(self):
        nodes = self.api_get('org-chart').json()['nodes']
        self.assertEqual(len(nodes), 1)
        top = nodes[0]
        self.assertEqual(
            set(top),
            {'id', 'parent_id', 'name', 'type', 'owner', 'is_vacant', 'order', 'responsibilities', 'children'},
        )
        self.assertEqual((top['id'], top['parent_id'], top['type']), (self.top.pk, None, 'role'))
        self.assertEqual(top['owner'], {'id': self.user.pk, 'name': self.user.username})
        self.assertEqual([child['id'] for child in top['children']], [self.ops.pk, self.sales.pk])
        ops, sales = top['children']
        self.assertEqual((ops['owner']['name'], ops['is_vacant'], ops['parent_id']), ('Mo Member', False, self.top.pk))
        self.assertEqual([duty['description'] for duty in ops['responsibilities']], ['Budget', 'Rotas'])
        self.assertEqual((sales['type'], sales['owner'], sales['is_vacant']), ('department', None, True))
        self.assertEqual([child['name'] for child in sales['children']], ['Sales rep'])
        self.assertEqual(sales['children'][0]['children'], [])

    def test_member_and_admin_see_the_same_chart_as_on_the_web(self):
        self.assertEqual(self.api_get('org-chart', self.mo_token).json(), self.api_get('org-chart').json())
        self.client.force_login(self.mo)
        page = self.client.get('/accountability/')
        self.assertEqual([root.pk for root in page.context['roots']], [self.top.pk])

    def test_an_empty_chart(self):
        AccountabilityNode.objects.filter(organization=self.org).delete()
        self.assertEqual(self.api_get('org-chart').json(), {'nodes': []})

    def test_a_deeper_chart_costs_no_more_queries(self):
        before = self.count_queries('org-chart')
        below = AccountabilityNode.objects.create(organization=self.org, parent=self.rep, name='Trainee', owner=self.mo)
        AccountabilityNode.objects.create(organization=self.org, parent=below, name='Apprentice')
        self.assertEqual(self.count_queries('org-chart'), before)
