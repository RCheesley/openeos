"""Shared fixtures: an application, and tokens issued the way the token endpoint issues them."""
import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from oauth2_provider.models import (
    AccessToken, Application, RefreshToken, set_token_value,
)

from apps.accounts.tests.test_isolation import build_org
from apps.api import scopes
from apps.api.models import Connection, ConnectionCredential, OrganizationApiAccess

ALL_SCOPES = ' '.join(scopes.SCOPES)
REDIRECT_URI = 'http://127.0.0.1:8765/callback'


def make_application(name='Test client', redirect_uris=REDIRECT_URI):
    return Application.objects.create(
        name=name, client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE, redirect_uris=redirect_uris,
    )


def enable_api(org, enabled=True):
    OrganizationApiAccess.objects.update_or_create(organization=org, defaults={'enabled': enabled})


def issue_token(user, org, scope=ALL_SCOPES, application=None, resource=(), expires_in=3600):
    """Create a connection and an access token for it; return the raw token string."""
    application = application or Application.objects.first() or make_application()
    connection, _ = Connection.objects.get_or_create(
        user=user, application=application, organization=org, defaults={'scope': scope},
    )
    raw = secrets.token_urlsafe(32)
    token = AccessToken(
        user=user, application=application, scope=scope, resource=list(resource),
        expires=timezone.now() + timedelta(seconds=expires_in),
    )
    set_token_value(token, raw)
    token.save()
    ConnectionCredential.objects.create(connection=connection, access_token=token)
    return raw


def bearer(raw):
    return {'HTTP_AUTHORIZATION': f'Bearer {raw}'}


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def query_of(url):
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


class ApiTestCase(TestCase):
    """Two organisations with the API on, and a token for the first one's admin."""

    def setUp(self):
        cache.clear()  # throttle counts live in the cache
        self.mine = build_org('Mine')
        self.theirs = build_org('Theirs')
        enable_api(self.mine['org'])
        enable_api(self.theirs['org'])
        self.application = make_application()
        self.user = self.mine['user']
        self.org = self.mine['org']
        self.token = issue_token(self.user, self.org)

    def api_get(self, path, token=None, **extra):
        return self.client.get(f'/api/v1/{path}', **bearer(token or self.token), **extra)

    def results(self, path, token=None):
        response = self.api_get(path, token)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['results']

    def assertProblem(self, response, status):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response['Content-Type'], 'application/problem+json')
        body = response.json()
        self.assertEqual(body['status'], status)
        self.assertEqual(body['type'], 'about:blank')
        self.assertIn('title', body)
        return body


__all__ = [
    'ALL_SCOPES', 'REDIRECT_URI', 'AccessToken', 'ApiTestCase', 'Application', 'RefreshToken',
    'bearer', 'enable_api', 'issue_token', 'make_application', 'pkce_pair', 'query_of',
]
