"""The documents an OAuth or MCP client reads to find its way: RFC 8414 and RFC 9728."""
from django.test import TestCase

from apps.api import scopes


class AuthorizationServerMetadataTest(TestCase):
    def setUp(self):
        response = self.client.get('/.well-known/oauth-authorization-server')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.meta = response.json()

    def test_required_fields(self):
        self.assertEqual(self.meta['issuer'], 'http://testserver')
        self.assertEqual(self.meta['authorization_endpoint'], 'http://testserver/o/authorize/')
        self.assertEqual(self.meta['token_endpoint'], 'http://testserver/o/token/')
        self.assertEqual(self.meta['revocation_endpoint'], 'http://testserver/o/revoke_token/')
        self.assertEqual(self.meta['response_types_supported'], ['code'])

    def test_only_what_oauth_2_1_allows_is_advertised(self):
        self.assertEqual(self.meta['grant_types_supported'], ['authorization_code', 'refresh_token'])
        self.assertEqual(self.meta['code_challenge_methods_supported'], ['S256'])
        self.assertIn('none', self.meta['token_endpoint_auth_methods_supported'])
        self.assertIs(self.meta['authorization_response_iss_parameter_supported'], True)

    def test_scopes_are_listed(self):
        self.assertEqual(self.meta['scopes_supported'], sorted(scopes.SCOPES))

    def test_registration_is_in_advance_only(self):
        self.assertNotIn('registration_endpoint', self.meta)
        self.assertIs(self.meta['client_id_metadata_document_supported'], False)

    def test_nothing_unrouted_is_advertised(self):
        for key in ('introspection_endpoint', 'device_authorization_endpoint', 'jwks_uri', 'userinfo_endpoint'):
            self.assertNotIn(key, self.meta)


class ProtectedResourceMetadataTest(TestCase):
    def test_document_for_the_api(self):
        response = self.client.get('/.well-known/oauth-protected-resource/api/v1')
        self.assertEqual(response.status_code, 200)
        meta = response.json()
        self.assertEqual(meta['resource'], 'http://testserver/api/v1')
        self.assertEqual(meta['authorization_servers'], ['http://testserver'])
        self.assertEqual(meta['scopes_supported'], sorted(scopes.SCOPES))
        self.assertEqual(meta['bearer_methods_supported'], ['header'])
        self.assertEqual(meta['resource_documentation'], 'http://testserver/api/v1/docs')
        self.assertTrue(meta['resource_name'])

    def test_document_at_the_origin(self):
        meta = self.client.get('/.well-known/oauth-protected-resource').json()
        self.assertEqual(meta['resource'], 'http://testserver')
        self.assertEqual(meta['authorization_servers'], ['http://testserver'])

    def test_the_issuer_matches_between_the_two_documents(self):
        server = self.client.get('/.well-known/oauth-authorization-server').json()
        resource = self.client.get('/.well-known/oauth-protected-resource/api/v1').json()
        self.assertEqual(resource['authorization_servers'], [server['issuer']])

    def test_documents_follow_the_host_they_are_asked_on(self):
        with self.settings(ALLOWED_HOSTS=['acme.example.test']):
            meta = self.client.get('/.well-known/oauth-protected-resource/api/v1', HTTP_HOST='acme.example.test').json()
        self.assertEqual(meta['resource'], 'http://acme.example.test/api/v1')
        self.assertEqual(meta['authorization_servers'], ['http://acme.example.test'])
