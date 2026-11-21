"""No token reaches another organisation's records, by list or by id."""
from django.urls import get_resolver

from apps.accounts.models import Membership
from apps.accounts.tests.test_isolation import build_org
from apps.scorecards.models import Scorecard

from .helpers import ApiTestCase, enable_api, issue_token


def pk_paths(f):
    """Every API path that reaches a record by primary key."""
    return [
        f'teams/{f["team"].pk}',
        f'priorities/{f["rock"].pk}',
        f'priorities/{f["rock"].pk}/steps',
        f'priorities/{f["rock"].pk}/check-ins',
        f'actions/{f["todo"].pk}',
        f'blockers/{f["issue"].pk}',
        f'metrics-boards/{f["scorecard"].pk}',
        f'metrics-boards/{f["scorecard"].pk}/metrics',
        f'metrics-boards/{f["scorecard"].pk}/metrics/{f["metric"].pk}/entries',
        f'meetings/{f["meeting"].pk}',
    ]


LIST_PATHS = ['teams', 'priorities', 'actions', 'blockers', 'metrics-boards', 'meetings']


class ApiIsolationTest(ApiTestCase):
    def test_other_organisations_records_are_not_found_by_id(self):
        for path in pk_paths(self.theirs):
            with self.subTest(path=path):
                self.assertProblem(self.api_get(path), 404)

    def test_own_records_are_found_by_id(self):
        for path in pk_paths(self.mine):
            with self.subTest(path=path):
                self.assertEqual(self.api_get(path).status_code, 200)

    def test_missing_and_foreign_records_look_the_same(self):
        foreign = self.api_get(f'priorities/{self.theirs["rock"].pk}')
        missing = self.api_get('priorities/999999999')
        self.assertEqual(foreign.status_code, missing.status_code)
        self.assertEqual(foreign.json(), missing.json())

    def test_lists_hold_only_the_tokens_organisation(self):
        theirs = {key: self.theirs[key].pk for key in ('team', 'rock', 'todo', 'issue')}
        expected = {
            'teams': [self.mine['team'].pk],
            'priorities': sorted(r.pk for r in self.mine['team'].rocks.all()),
            'actions': [self.mine['todo'].pk],
            'blockers': [self.mine['issue'].pk],
            'metrics-boards': [self.mine['scorecard'].pk],
            'meetings': [self.mine['meeting'].pk],
        }
        for path in LIST_PATHS:
            with self.subTest(path=path):
                ids = [row['id'] for row in self.results(path)]
                self.assertEqual(ids, expected[path])
        self.assertNotIn(theirs['rock'], [row['id'] for row in self.results('priorities')])

    def test_filtering_by_another_organisations_team_finds_nothing(self):
        for path in ('priorities', 'actions', 'blockers', 'metrics-boards', 'meetings'):
            with self.subTest(path=path):
                self.assertEqual(self.results(f'{path}?team={self.theirs["team"].pk}'), [])

    def test_organisation_and_me_describe_the_tokens_organisation(self):
        self.assertEqual(self.api_get('organisation').json()['id'], self.org.pk)
        self.assertEqual(self.api_get('me').json()['organisation'], {'id': self.org.pk, 'name': 'Mine Org'})

    def test_a_metric_is_not_reached_through_another_organisations_board(self):
        """Both ids in the address are checked, in either combination."""
        mine, theirs = self.mine, self.theirs
        for board, metric in ((mine, theirs), (theirs, mine)):
            with self.subTest(board=board['org'].name):
                path = f'metrics-boards/{board["scorecard"].pk}/metrics/{metric["metric"].pk}/entries'
                self.assertProblem(self.api_get(path), 404)

    def test_a_metric_is_not_reached_through_another_board_of_the_same_organisation(self):
        other = Scorecard.objects.create(name='Other board', team=self.mine['team'])
        path = f'metrics-boards/{other.pk}/metrics/{self.mine["metric"].pk}/entries'
        self.assertProblem(self.api_get(path), 404)

    def test_vision_document_and_org_chart_are_the_tokens_organisations(self):
        board = self.api_get('vision-board').json()
        self.assertEqual([value['name'] for value in board['values']], ['Mine Value'])
        chart = self.api_get('org-chart').json()
        self.assertEqual([node['name'] for node in chart['nodes']], ['Mine Seat'])
        self.assertEqual(
            [duty['description'] for duty in chart['nodes'][0]['responsibilities']], ['Mine duty'],
        )
        self.assertNotIn('Theirs', str(board) + str(chart))

    def test_every_pk_route_is_covered_here(self):
        """A new by-id route must be added to pk_paths, or this fails."""
        routes = set()
        for pattern in get_resolver('apps.api.urls').url_patterns:
            route = str(pattern.pattern)
            if '<' in route:
                routes.add(route)
        covered = {
            'teams/<int:pk>', 'priorities/<int:pk>', 'priorities/<int:pk>/steps',
            'priorities/<int:pk>/check-ins', 'actions/<int:pk>', 'blockers/<int:pk>',
            'metrics-boards/<int:pk>', 'metrics-boards/<int:pk>/metrics',
            'metrics-boards/<int:pk>/metrics/<int:metric_id>/entries', 'meetings/<int:pk>',
        }
        self.assertEqual(routes, covered)
        self.assertEqual(len(pk_paths(self.mine)), len(covered))


class MemberOfTwoOrganisationsTest(ApiTestCase):
    """Belonging to both organisations does not widen a token: it acts in one."""

    def setUp(self):
        super().setUp()
        Membership.objects.create(user=self.user, organization=self.theirs['org'], role=Membership.ROLE_ADMIN)
        self.user.profile.teams.add(self.theirs['team'])

    def test_token_reads_only_its_own_organisation(self):
        for path in pk_paths(self.theirs):
            with self.subTest(path=path):
                self.assertProblem(self.api_get(path), 404)
        self.assertEqual([row['id'] for row in self.results('teams')], [self.mine['team'].pk])
        self.assertEqual([row['id'] for row in self.results('actions')], [self.mine['todo'].pk])

    def test_a_second_connection_reads_the_other_organisation(self):
        other = issue_token(self.user, self.theirs['org'])
        self.assertEqual(self.api_get('organisation', token=other).json()['name'], 'Theirs Org')
        for path in pk_paths(self.theirs):
            with self.subTest(path=path):
                self.assertEqual(self.api_get(path, token=other).status_code, 200)
        for path in pk_paths(self.mine):
            with self.subTest(path=path):
                self.assertProblem(self.api_get(path, token=other), 404)

    def test_a_third_organisation_without_membership_stays_closed(self):
        third = build_org('Third')
        enable_api(third['org'])
        for path in pk_paths(third):
            with self.subTest(path=path):
                self.assertProblem(self.api_get(path), 404)
