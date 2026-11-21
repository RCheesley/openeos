"""Sign-in end to end: authorisation code with PKCE, consent, tokens, rotation, revocation."""
import hashlib
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.test import override_settings

from apps.accounts.models import Membership, OrganizationDomain
from apps.api.models import Connection
from apps.audit.models import AuditEvent

from .helpers import (
    REDIRECT_URI, AccessToken, ApiTestCase, Application, RefreshToken, enable_api, make_application,
    pkce_pair, query_of,
)

SCOPE = 'organisation:read priorities:read'


class FlowMixin:
    def authorize_params(self, challenge, **overrides):
        params = {
            'response_type': 'code', 'client_id': self.application.client_id,
            'redirect_uri': REDIRECT_URI, 'scope': SCOPE, 'state': 'xyz',
            'code_challenge': challenge, 'code_challenge_method': 'S256',
        }
        params.update(overrides)
        return {key: value for key, value in params.items() if value is not None}

    def consent(self, challenge, organization=None, allow=True, **overrides):
        """Open the consent screen and submit it; return the redirect back to the client."""
        params = self.authorize_params(challenge, **overrides)
        page = self.client.get('/o/authorize/', params)
        self.assertEqual(page.status_code, 200, page.content)
        data = dict(page.context['form'].initial)
        data = {key: value for key, value in data.items() if value is not None}
        data['organization'] = (organization or self.org).pk
        if allow:
            data['allow'] = 'Authorize'
        response = self.client.post('/o/authorize/?' + urlencode(params), data)
        self.assertEqual(response.status_code, 302, response.content)
        return response['Location']

    def exchange(self, code, verifier, **overrides):
        data = {
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI,
            'client_id': self.application.client_id, 'code_verifier': verifier,
        }
        data.update(overrides)
        return self.client.post('/o/token/', data)

    def refresh(self, refresh_token):
        return self.client.post('/o/token/', {
            'grant_type': 'refresh_token', 'refresh_token': refresh_token,
            'client_id': self.application.client_id,
        })

    def sign_in(self, **consent_kwargs):
        """The whole flow; returns the token response body."""
        verifier, challenge = pkce_pair()
        location = self.consent(challenge, **consent_kwargs)
        response = self.exchange(query_of(location)['code'], verifier)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class AuthorizationCodeFlowTest(FlowMixin, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_full_flow_reads_the_api(self):
        verifier, challenge = pkce_pair()
        location = self.consent(challenge)
        self.assertTrue(location.startswith(REDIRECT_URI + '?'))
        answer = query_of(location)
        self.assertEqual(answer['state'], 'xyz')
        self.assertEqual(answer['iss'], 'http://testserver')  # RFC 9207

        response = self.exchange(answer['code'], verifier)
        self.assertEqual(response.status_code, 200, response.content)
        tokens = response.json()
        self.assertEqual(tokens['token_type'], 'Bearer')
        self.assertEqual(tokens['scope'], SCOPE)
        self.assertEqual(tokens['expires_in'], 3600)
        self.assertIn('refresh_token', tokens)

        self.client.logout()  # the API call below rides on the token alone
        me = self.api_get('me', token=tokens['access_token'])
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()['organisation']['id'], self.org.pk)
        self.assertEqual(self.api_get('priorities', token=tokens['access_token']).status_code, 200)
        self.assertProblem(self.api_get('actions', token=tokens['access_token']), 403)  # not asked for

    def test_tokens_are_stored_hashed(self):
        tokens = self.sign_in()
        for model, raw in ((AccessToken, tokens['access_token']), (RefreshToken, tokens['refresh_token'])):
            with self.subTest(model=model.__name__):
                self.assertFalse(model.objects.filter(token=raw).exists())
                self.assertFalse(model.objects.exclude(token='').exists())
                checksum = hashlib.sha256(raw.encode()).hexdigest()
                self.assertTrue(model.objects.filter(token_checksum=checksum).exists())

    def test_token_is_bound_to_the_address_it_was_issued_for(self):
        tokens = self.sign_in()
        token = AccessToken.objects.get(token_checksum=hashlib.sha256(tokens['access_token'].encode()).hexdigest())
        self.assertEqual(token.resource, ['http://testserver/api/v1'])
        with self.settings(ALLOWED_HOSTS=['testserver', 'elsewhere.example.test']):
            self.assertProblem(
                self.api_get('me', token=tokens['access_token'], HTTP_HOST='elsewhere.example.test'), 401
            )

    def test_anonymous_visitor_is_sent_to_the_normal_login(self):
        self.client.logout()
        _, challenge = pkce_pair()
        response = self.client.get('/o/authorize/', self.authorize_params(challenge))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/?next='))

    def test_request_without_pkce_is_refused(self):
        response = self.client.get(
            '/o/authorize/', self.authorize_params(None, code_challenge_method=None)
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_of(response['Location'])['error'], 'invalid_request')

    def test_plain_pkce_is_refused(self):
        verifier, _ = pkce_pair()
        params = self.authorize_params(verifier, code_challenge_method='plain')
        page = self.client.get('/o/authorize/', params)
        if page.status_code == 200:
            data = {k: v for k, v in page.context['form'].initial.items() if v is not None}
            data.update({'organization': self.org.pk, 'allow': 'Authorize'})
            page = self.client.post('/o/authorize/?' + urlencode(params), data)
        self.assertEqual(page.status_code, 302)
        self.assertIn('error', query_of(page['Location']))
        self.assertFalse(AccessToken.objects.filter(application=self.application, scope=SCOPE).exists())

    def test_wrong_verifier_is_refused(self):
        _, challenge = pkce_pair()
        code = query_of(self.consent(challenge))['code']
        response = self.exchange(code, 'x' * 64)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'invalid_grant')

    def test_code_works_once(self):
        verifier, challenge = pkce_pair()
        code = query_of(self.consent(challenge))['code']
        self.assertEqual(self.exchange(code, verifier).status_code, 200)
        self.assertEqual(self.exchange(code, verifier).status_code, 400)

    def test_unregistered_redirect_is_refused_without_redirecting(self):
        _, challenge = pkce_pair()
        response = self.client.get(
            '/o/authorize/', self.authorize_params(challenge, redirect_uri='https://evil.example/cb')
        )
        self.assertEqual(response.status_code, 400)

    def test_http_redirect_is_for_loopback_only(self):
        self.application.redirect_uris = REDIRECT_URI + ' http://app.example.test/cb'
        self.application.save()
        _, challenge = pkce_pair()
        response = self.client.get(
            '/o/authorize/', self.authorize_params(challenge, redirect_uri='http://app.example.test/cb')
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_scope_is_refused(self):
        _, challenge = pkce_pair()
        response = self.client.get('/o/authorize/', self.authorize_params(challenge, scope='priorities:write'))
        self.assertEqual(query_of(response['Location'])['error'], 'invalid_scope')

    def test_resource_on_another_host_is_refused(self):
        _, challenge = pkce_pair()
        response = self.client.get(
            '/o/authorize/', self.authorize_params(challenge, resource='https://other.example/api/v1')
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_of(response['Location'])['error'], 'invalid_target')

    def test_resource_named_by_the_client_is_kept(self):
        tokens = self.sign_in(resource='http://testserver/api/v1')
        token = AccessToken.objects.get(token_checksum=hashlib.sha256(tokens['access_token'].encode()).hexdigest())
        self.assertEqual(token.resource, ['http://testserver/api/v1'])

    def test_other_grant_types_are_refused(self):
        confidential = Application.objects.create(
            name='Machine', client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS,
            client_id='machine', client_secret='s3cret', hash_client_secret=False,
        )
        response = self.client.post('/o/token/', {
            'grant_type': 'client_credentials', 'client_id': confidential.client_id, 'client_secret': 's3cret',
        })
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/o/token/', {
            'grant_type': 'password', 'username': self.user.username, 'password': 'pw',
            'client_id': self.application.client_id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AccessToken.objects.filter(application=confidential).count(), 0)

    def test_implicit_flow_is_refused(self):
        response = self.client.get('/o/authorize/', {
            'response_type': 'token', 'client_id': self.application.client_id,
            'redirect_uri': REDIRECT_URI, 'scope': SCOPE,
        })
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn('access_token', response.get('Location', ''))


class ConsentScreenTest(FlowMixin, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        _, self.challenge = pkce_pair()

    def page(self, **extra):
        return self.client.get('/o/authorize/', self.authorize_params(self.challenge), **extra)

    def test_names_the_application_the_organisation_and_the_scopes(self):
        html = self.page().content.decode()
        self.assertIn('Test client', html)
        self.assertIn('Mine Org', html)
        self.assertIn('See priorities, their steps and check-ins', html)
        self.assertNotIn('Theirs Org', html)

    def test_member_of_several_organisations_picks_one(self):
        Membership.objects.create(user=self.user, organization=self.theirs['org'])
        self.assertEqual({org.name for org in self.page().context['organizations']}, {'Mine Org', 'Theirs Org'})
        tokens = self.sign_in(organization=self.theirs['org'])
        self.client.logout()
        self.assertEqual(self.api_get('organisation', token=tokens['access_token']).json()['name'], 'Theirs Org')

    def test_only_organisations_with_the_api_on_are_offered(self):
        Membership.objects.create(user=self.user, organization=self.theirs['org'])
        enable_api(self.theirs['org'], False)
        self.assertEqual([org.name for org in self.page().context['organizations']], ['Mine Org'])

    def test_cannot_connect_to_an_organisation_one_does_not_belong_to(self):
        params = self.authorize_params(self.challenge)
        data = {k: v for k, v in self.page().context['form'].initial.items() if v is not None}
        data.update({'organization': self.theirs['org'].pk, 'allow': 'Authorize'})
        response = self.client.post('/o/authorize/?' + urlencode(params), data)
        self.assertEqual(response.status_code, 200)  # the form again, with an error
        self.assertFalse(Connection.objects.filter(organization=self.theirs['org']).exists())

    def test_no_organisation_with_the_api_on_means_nothing_to_connect(self):
        enable_api(self.org, False)
        page = self.page()
        self.assertContains(page, 'API access is not switched on')
        self.assertNotContains(page, 'name="allow"')

    @override_settings(ALLOWED_HOSTS=['testserver', 'theirs.example.test'])
    def test_on_an_organisations_own_hostname_the_organisation_is_fixed(self):
        Membership.objects.create(user=self.user, organization=self.theirs['org'])
        OrganizationDomain.objects.create(organization=self.theirs['org'], hostname='theirs.example.test')
        page = self.page(HTTP_HOST='theirs.example.test')
        self.assertEqual([org.name for org in page.context['organizations']], ['Theirs Org'])

    def test_cancel_returns_access_denied_and_is_logged(self):
        location = self.consent(self.challenge, allow=False)
        self.assertEqual(query_of(location)['error'], 'access_denied')
        self.assertTrue(AuditEvent.objects.filter(action='api.connection.denied', actor=self.user).exists())
        self.assertFalse(Connection.objects.filter(application=self.application, scope=SCOPE).exists())

    def test_approval_is_logged(self):
        self.sign_in()
        event = AuditEvent.objects.get(action='api.connection.approved')
        self.assertEqual((event.actor, event.organization), (self.user, self.org))
        self.assertEqual(event.details['scope'], SCOPE)

    def test_application_that_skips_consent_cannot_choose_an_organisation(self):
        self.application.skip_authorization = True
        self.application.save()
        response = self.page()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(query_of(response['Location'])['error'], 'access_denied')


class RefreshAndRevocationTest(FlowMixin, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.tokens = self.sign_in()
        self.client.logout()

    def test_refresh_rotates_both_tokens_and_keeps_the_organisation(self):
        response = self.refresh(self.tokens['refresh_token'])
        self.assertEqual(response.status_code, 200, response.content)
        fresh = response.json()
        self.assertNotEqual(fresh['access_token'], self.tokens['access_token'])
        self.assertNotEqual(fresh['refresh_token'], self.tokens['refresh_token'])
        self.assertProblem(self.api_get('me', token=self.tokens['access_token']), 401)
        me = self.api_get('me', token=fresh['access_token'])
        self.assertEqual(me.json()['organisation']['id'], self.org.pk)
        again = self.refresh(fresh['refresh_token']).json()
        self.assertEqual(self.api_get('me', token=again['access_token']).status_code, 200)

    def test_replaying_a_used_refresh_token_ends_the_whole_family(self):
        fresh = self.refresh(self.tokens['refresh_token']).json()
        replay = self.refresh(self.tokens['refresh_token'])
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()['error'], 'invalid_grant')
        self.assertProblem(self.api_get('me', token=fresh['access_token']), 401)
        self.assertEqual(self.refresh(fresh['refresh_token']).status_code, 400)

    def test_refresh_is_refused_once_the_api_is_switched_off(self):
        enable_api(self.org, False)
        self.assertEqual(self.refresh(self.tokens['refresh_token']).status_code, 400)

    def test_refresh_is_refused_once_the_user_has_left(self):
        Membership.objects.filter(user=self.user, organization=self.org).delete()
        self.assertEqual(self.refresh(self.tokens['refresh_token']).status_code, 400)

    def test_client_can_revoke_its_token(self):
        response = self.client.post('/o/revoke_token/', {
            'token': self.tokens['access_token'], 'client_id': self.application.client_id,
        })
        self.assertEqual(response.status_code, 200)
        self.assertProblem(self.api_get('me', token=self.tokens['access_token']), 401)
        self.assertEqual(self.refresh(self.tokens['refresh_token']).status_code, 400)

    def test_user_disconnects_from_their_profile(self):
        connection = Connection.objects.get(application=self.application, scope=SCOPE)
        self.client.force_login(self.user)
        page = self.client.get('/profile/connections/')
        self.assertContains(page, 'Test client')
        response = self.client.post(f'/profile/connections/{connection.pk}/revoke/')
        self.assertRedirects(response, '/profile/connections/')
        self.client.logout()
        self.assertProblem(self.api_get('me', token=self.tokens['access_token']), 401)
        self.assertEqual(self.refresh(self.tokens['refresh_token']).status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action='api.connection.revoked').exists())

    def test_connecting_again_after_disconnecting_works(self):
        Connection.objects.get(application=self.application, scope=SCOPE).revoke()
        self.client.force_login(self.user)
        tokens = self.sign_in()
        self.client.logout()
        self.assertEqual(self.api_get('me', token=tokens['access_token']).status_code, 200)
        self.assertProblem(self.api_get('me', token=self.tokens['access_token']), 401)


class WebPagesTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.member = User.objects.create_user('member', password='pw')
        Membership.objects.create(user=self.member, organization=self.org, role=Membership.ROLE_MEMBER)

    def test_admin_switches_the_api_off_and_on(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/org/settings/api/'), 'checked')
        self.client.post('/org/settings/api/', {})
        self.assertProblem(self.api_get('me'), 401)
        self.assertTrue(AuditEvent.objects.filter(action='api.access.disabled', organization=self.org).exists())
        self.client.post('/org/settings/api/', {'enabled': 'on'})
        self.assertEqual(self.api_get('me').status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action='api.access.enabled', organization=self.org).exists())

    def test_member_cannot_reach_the_switch(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get('/org/settings/api/').status_code, 403)
        self.assertEqual(self.client.post('/org/settings/api/', {}).status_code, 403)
        self.assertEqual(self.api_get('me').status_code, 200)

    def test_admin_sees_and_ends_a_members_connection(self):
        from .helpers import issue_token
        member_token = issue_token(self.member, self.org)
        connection = Connection.objects.get(user=self.member)
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/org/settings/api/'), 'member')
        self.assertRedirects(
            self.client.post(f'/profile/connections/{connection.pk}/revoke/'), '/org/settings/api/'
        )
        self.assertProblem(self.api_get('me', token=member_token), 401)

    def test_nobody_else_can_end_a_connection(self):
        connection = Connection.objects.get(user=self.user)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(f'/profile/connections/{connection.pk}/revoke/').status_code, 404)
        outsider = self.theirs['user']
        self.client.force_login(outsider)
        self.assertEqual(self.client.post(f'/profile/connections/{connection.pk}/revoke/').status_code, 404)
        self.assertEqual(self.api_get('me').status_code, 200)

    def test_connections_page_lists_only_ones_own(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get('/profile/connections/'), 'No applications are connected')

    def test_tokens_are_left_out_of_the_organisation_export(self):
        from apps.accounts.portability import PORTABLE_APPS
        self.assertNotIn('api', PORTABLE_APPS)
        self.assertNotIn('oauth2_provider', PORTABLE_APPS)
