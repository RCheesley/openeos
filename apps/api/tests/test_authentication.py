from django.contrib.auth.models import User
from django.test import override_settings

from apps.accounts.models import Membership, OrganizationDomain
from apps.api import scopes
from apps.api.models import Connection

from .helpers import ApiTestCase, enable_api, issue_token

HOSTS = ['testserver', 'mine.example.test', 'theirs.example.test']


class TokenRequiredTest(ApiTestCase):
    def test_no_token_is_refused_and_told_where_to_sign_in(self):
        response = self.client.get('/api/v1/teams')
        self.assertProblem(response, 401)
        challenge = response['WWW-Authenticate']
        self.assertTrue(challenge.startswith('Bearer '))
        self.assertIn(
            'resource_metadata="http://testserver/.well-known/oauth-protected-resource/api/v1"', challenge
        )

    def test_a_browser_session_is_not_accepted(self):
        self.client.force_login(self.user)
        # The session is good for the web...
        self.assertEqual(self.client.get('/teams/').status_code, 200)
        # ...and counts for nothing on the API.
        for path in ('organisation', 'me', 'teams', 'priorities', 'actions', 'blockers',
                     f'priorities/{self.mine["rock"].pk}'):
            with self.subTest(path=path):
                self.assertProblem(self.client.get(f'/api/v1/{path}'), 401)

    def test_unknown_token_is_refused(self):
        self.assertProblem(self.api_get('teams', token='not-a-token'), 401)

    def test_expired_token_is_refused(self):
        expired = issue_token(self.user, self.org, expires_in=-1)
        self.assertProblem(self.api_get('teams', token=expired), 401)

    def test_token_in_the_query_string_is_refused(self):
        self.assertProblem(self.client.get(f'/api/v1/teams?access_token={self.token}'), 401)

    def test_valid_token_is_accepted(self):
        response = self.api_get('me')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json()['username'], self.user.username)

    def test_token_without_a_connection_is_refused(self):
        raw = issue_token(self.user, self.org)
        Connection.objects.all().delete()  # leaves the token row, takes its organisation away
        self.assertProblem(self.api_get('me', token=raw), 401)

    def test_the_api_is_read_only(self):
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    f'/api/v1/priorities/{self.mine["rock"].pk}', data='{"title": "Changed"}',
                    content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {self.token}',
                )
                self.assertProblem(response, 405)
        self.mine['rock'].refresh_from_db()
        self.assertEqual(self.mine['rock'].title, 'Mine Rock')

    def test_unknown_endpoint_answers_in_the_api_error_format(self):
        self.assertProblem(self.api_get('no-such-thing'), 404)
        self.assertProblem(self.client.get('/api/v1/no-such-thing'), 404)


class ScopeTest(ApiTestCase):
    ENDPOINTS = {
        'organisation': scopes.ORGANISATION_READ,
        'teams': scopes.TEAMS_READ,
        'teams/{team}': scopes.TEAMS_READ,
        'priorities': scopes.PRIORITIES_READ,
        'priorities/{rock}': scopes.PRIORITIES_READ,
        'priorities/{rock}/steps': scopes.PRIORITIES_READ,
        'priorities/{rock}/check-ins': scopes.PRIORITIES_READ,
        'actions': scopes.ACTIONS_READ,
        'actions/{todo}': scopes.ACTIONS_READ,
        'blockers': scopes.BLOCKERS_READ,
        'blockers/{issue}': scopes.BLOCKERS_READ,
        'metrics-boards': scopes.METRICS_BOARDS_READ,
        'metrics-boards/{scorecard}': scopes.METRICS_BOARDS_READ,
        'metrics-boards/{scorecard}/metrics': scopes.METRICS_BOARDS_READ,
        'metrics-boards/{scorecard}/metrics/{metric}/entries': scopes.METRICS_BOARDS_READ,
        'meetings': scopes.MEETINGS_READ,
        'meetings/{meeting}': scopes.MEETINGS_READ,
        'vision-board': scopes.VISION_BOARD_READ,
        'org-chart': scopes.ORG_CHART_READ,
    }

    def test_every_route_is_listed_here(self):
        from django.urls import get_resolver
        named = {p.name for p in get_resolver('apps.api.urls').url_patterns if getattr(p, 'name', None)}
        open_to_all = {'schema', 'docs', 'docs-sign-in-return', 'me'}
        self.assertEqual(len(named - open_to_all), len(self.ENDPOINTS))

    def paths(self):
        ids = {key: self.mine[key].pk for key in ('team', 'rock', 'todo', 'issue', 'scorecard', 'metric', 'meeting')}
        return {template.format(**ids): scope for template, scope in self.ENDPOINTS.items()}

    def test_each_endpoint_needs_its_own_scope(self):
        tokens = {scope: issue_token(self.user, self.org, scope=scope) for scope in scopes.SCOPES}
        for path, needed in self.paths().items():
            for held, token in tokens.items():
                with self.subTest(path=path, held=held):
                    response = self.api_get(path, token=token)
                    if held == needed:
                        self.assertEqual(response.status_code, 200, response.content)
                    else:
                        self.assertProblem(response, 403)

    def test_me_needs_a_token_but_no_particular_scope(self):
        token = issue_token(self.user, self.org, scope=scopes.ACTIONS_READ)
        response = self.api_get('me', token=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['scopes'], [scopes.ACTIONS_READ])

    def test_a_scope_the_server_does_not_define_grants_nothing(self):
        token = issue_token(self.user, self.org, scope='priorities:write everything')
        self.assertProblem(self.api_get('priorities', token=token), 403)


class ConnectionStillValidTest(ApiTestCase):
    """What ends a token's usefulness between one request and the next."""

    def test_switching_the_api_off_for_the_organisation(self):
        self.assertEqual(self.api_get('me').status_code, 200)
        enable_api(self.org, False)
        self.assertProblem(self.api_get('me'), 401)

    def test_api_is_off_until_an_admin_switches_it_on(self):
        fresh = User.objects.create_user('fresh', password='pw')
        from apps.accounts.models import Organization
        org = Organization.objects.create(name='Fresh Org')
        Membership.objects.create(user=fresh, organization=org, role=Membership.ROLE_ADMIN)
        self.assertProblem(self.api_get('me', token=issue_token(fresh, org)), 401)

    def test_leaving_the_organisation(self):
        Membership.objects.filter(user=self.user, organization=self.org).delete()
        self.assertProblem(self.api_get('me'), 401)

    def test_deactivating_the_user(self):
        self.user.is_active = False
        self.user.save()
        self.assertProblem(self.api_get('me'), 401)

    def test_revoking_the_connection(self):
        Connection.objects.get(user=self.user, organization=self.org).revoke()
        self.assertProblem(self.api_get('me'), 401)

    def test_last_use_is_recorded(self):
        connection = Connection.objects.get(user=self.user, organization=self.org)
        self.assertIsNone(connection.last_used_at)
        self.api_get('me')
        connection.refresh_from_db()
        self.assertIsNotNone(connection.last_used_at)


@override_settings(ALLOWED_HOSTS=HOSTS)
class HostBindingTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        OrganizationDomain.objects.create(organization=self.mine['org'], hostname='mine.example.test')
        OrganizationDomain.objects.create(organization=self.theirs['org'], hostname='theirs.example.test')

    def test_token_works_on_its_own_organisations_hostname(self):
        response = self.api_get('organisation', HTTP_HOST='mine.example.test')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Mine Org')

    def test_token_is_refused_on_another_organisations_hostname(self):
        self.assertProblem(self.api_get('organisation', HTTP_HOST='theirs.example.test'), 401)

    def test_member_of_both_is_still_held_to_the_tokens_organisation(self):
        Membership.objects.create(user=self.user, organization=self.theirs['org'])
        self.assertProblem(self.api_get('organisation', HTTP_HOST='theirs.example.test'), 401)

    def test_token_issued_for_one_address_is_refused_at_another(self):
        bound = issue_token(self.user, self.org, resource=['http://mine.example.test/api/v1'])
        self.assertEqual(self.api_get('me', token=bound, HTTP_HOST='mine.example.test').status_code, 200)
        response = self.api_get('me', token=bound)  # same server, reached as testserver
        self.assertProblem(response, 401)
        self.assertIn('invalid_token', response['WWW-Authenticate'])

    def test_token_for_the_api_is_not_good_for_a_sibling_path(self):
        bound = issue_token(self.user, self.org, resource=['http://testserver/api/v2'])
        self.assertProblem(self.api_get('me', token=bound), 401)
