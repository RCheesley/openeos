"""Token sign-in for the API.

django-oauth-toolkit checks the token itself: that it exists, has not expired
and was issued for this host. This class then works out the organisation and
applies the rules the web applies through the session and hostname middleware.
"""
from datetime import timedelta

from django.utils import timezone
from oauth2_provider.contrib.rest_framework import OAuth2ProtectedResourceAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts.scoping import pin_active_org

from .access import connection_usable
from .models import Connection, ConnectionCredential

# How often a connection's "last used" time is refreshed, to avoid a write per request.
LAST_USED_RESOLUTION = timedelta(minutes=5)

RESOURCE_METADATA_PATH = '/.well-known/oauth-protected-resource/api/v1'


class ApiTokenAuthentication(OAuth2ProtectedResourceAuthentication):
    www_authenticate_realm = 'api'

    def get_resource_metadata_url(self, request):
        return request.build_absolute_uri(RESOURCE_METADATA_PATH)

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        credential = (
            ConnectionCredential.objects
            .select_related('connection', 'connection__user', 'connection__organization')
            .filter(access_token=token)
            .first()
        )
        connection = credential.connection if credential else None
        # The hostname middleware ran before anyone knew who was calling, so the
        # pinned-host rule is applied here: a token for one organisation is
        # refused on another organisation's hostname.
        host_org = getattr(request, 'host_org', None)
        if user is None or not connection_usable(connection, host_org):
            request.oauth2_error = {
                'error': 'invalid_token',
                'error_description': 'The access token is not valid for this organisation.',
            }
            raise AuthenticationFailed('The access token is not valid for this organisation.')
        token.api_connection = connection
        token.organization = connection.organization
        pin_active_org(request._request, connection.organization)
        self._touch(connection)
        return user, token

    @staticmethod
    def _touch(connection):
        now = timezone.now()
        if connection.last_used_at is None or now - connection.last_used_at > LAST_USED_RESOLUTION:
            Connection.objects.filter(pk=connection.pk).update(last_used_at=now)
