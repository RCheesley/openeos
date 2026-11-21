"""The OpenAPI document: valid 3.2, complete, generic in its words, and in step with the committed copy."""
import re
from pathlib import Path

import yaml
from django.test import SimpleTestCase, TestCase
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema

from apps.api import scopes

COMMITTED = Path(__file__).resolve().parent.parent / 'openapi.yaml'

REGENERATE = 'python manage.py spectacular --file apps/api/openapi.yaml'


def generate():
    return SchemaGenerator().get_schema(request=None, public=True)


class SchemaTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = generate()

    def test_is_valid_openapi_3_2(self):
        self.assertEqual(self.schema['openapi'], '3.2.0')
        validate_schema(self.schema)  # raises if the document breaks the 3.2 schema

    def test_matches_the_committed_copy(self):
        committed = yaml.safe_load(COMMITTED.read_text())
        current = yaml.safe_load(yaml.safe_dump(self.schema))
        self.assertEqual(
            current, committed,
            f'The API changed without its committed description. Run: {REGENERATE}',
        )

    def test_paths(self):
        self.assertEqual(sorted(self.schema['paths']), [
            '/api/v1/actions', '/api/v1/actions/{id}',
            '/api/v1/blockers', '/api/v1/blockers/{id}',
            '/api/v1/me', '/api/v1/meetings', '/api/v1/meetings/{id}',
            '/api/v1/metrics-boards', '/api/v1/metrics-boards/{id}',
            '/api/v1/metrics-boards/{id}/metrics',
            '/api/v1/metrics-boards/{id}/metrics/{metric_id}/entries',
            '/api/v1/org-chart', '/api/v1/organisation',
            '/api/v1/priorities', '/api/v1/priorities/{id}',
            '/api/v1/priorities/{id}/check-ins', '/api/v1/priorities/{id}/steps',
            '/api/v1/teams', '/api/v1/teams/{id}',
            '/api/v1/vision-board',
        ])

    def test_every_operation_is_read_only_and_needs_a_token(self):
        for path, operations in self.schema['paths'].items():
            self.assertEqual(list(operations), ['get'], path)
            security = operations['get']['security']
            self.assertEqual(len(security), 1, path)
            self.assertIn('oauth2', security[0], path)
            for scope in security[0]['oauth2']:
                self.assertIn(scope, scopes.SCOPES, path)
            if path != '/api/v1/me':
                self.assertTrue(security[0]['oauth2'], f'{path} names no scope')

    def test_sign_in_is_authorisation_code_only(self):
        scheme = self.schema['components']['securitySchemes']['oauth2']
        self.assertEqual(list(scheme['flows']), ['authorizationCode'])
        flow = scheme['flows']['authorizationCode']
        self.assertEqual((flow['authorizationUrl'], flow['tokenUrl']), ('/o/authorize/', '/o/token/'))
        self.assertEqual(set(flow['scopes']), set(scopes.SCOPES))
        self.assertEqual(scheme['oauth2MetadataUrl'], '/.well-known/oauth-authorization-server')

    def test_errors_are_problem_details(self):
        responses = self.schema['paths']['/api/v1/priorities/{id}']['get']['responses']
        for code in ('401', '403', '404', '429'):
            self.assertEqual(
                responses[code]['content']['application/problem+json']['schema']['$ref'],
                '#/components/schemas/Problem',
            )

    def test_tags_are_nested(self):
        tags = {tag['name']: tag for tag in self.schema['tags']}
        self.assertEqual(tags['Steps']['parent'], 'Priorities')
        self.assertEqual(tags['Check-ins']['parent'], 'Priorities')
        self.assertEqual(tags['Metrics']['parent'], 'Metrics Boards')
        self.assertEqual(tags['Entries']['parent'], 'Metrics Boards')

    def test_every_tag_in_use_is_described(self):
        used = {tag for operations in self.schema['paths'].values() for tag in operations['get']['tags']}
        self.assertEqual(used, {tag['name'] for tag in self.schema['tags']})

    def test_the_org_chart_is_a_tree(self):
        node = self.schema['components']['schemas']['OrgChartNode']
        self.assertEqual(node['properties']['children']['items']['$ref'], '#/components/schemas/OrgChartNode')

    def test_only_generic_vocabulary_is_published(self):
        text = yaml.safe_dump(self.schema).lower()
        for word in ('rock', 'rocks', 'todo', 'to-do', 'issue', 'issues', 'scorecard', 'vto', 'segue', 'ids',
                     'milestone', 'level 10', 'l10', 'traction', 'eos', 'v/to', 'accountability', 'seat', 'seats',
                     'headline', 'headlines', 'cascading', 'core focus', 'core values', 'rocks review',
                     'ten_year_target', '10-year target', 'three_uniques', 'proven process'):
            with self.subTest(word=word):
                self.assertIsNone(re.search(rf'(?<![a-z_]){re.escape(word)}(?![a-z_])', text))


class SchemaEndpointTest(TestCase):
    def test_document_is_served_without_a_token(self):
        response = self.client.get('/api/v1/openapi.json', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['openapi'], '3.2.0')

    def test_docs_sign_in_return_page_is_served_beside_the_docs_page(self):
        # Swagger UI sends the pop-up back to ./oauth2-redirect.html after sign-in.
        response = self.client.get('/api/v1/oauth2-redirect.html?code=abc&state=xyz')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.content.decode(), r'<script src="/static/[^"]*oauth2-redirect[^"]*\.js">')

    def test_docs_and_return_page_keep_the_site_opener_policy(self):
        # The pop-up loses its link to the docs page if any page on the way differs.
        login = self.client.get('/accounts/login/')
        for url in ('/api/v1/docs', '/api/v1/oauth2-redirect.html'):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url)['Cross-Origin-Opener-Policy'],
                    login['Cross-Origin-Opener-Policy'],
                )

    def test_docs_page_loads_nothing_from_a_third_party(self):
        response = self.client.get('/api/v1/docs')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('/api/v1/openapi.json', html)
        self.assertNotIn('cdn.', html)
        for src in re.findall(r'(?:src|href)="([^"]+)"', html):
            self.assertTrue(src.startswith('/'), src)
