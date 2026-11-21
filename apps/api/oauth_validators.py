"""OAuth request validation on top of django-oauth-toolkit's.

Adds three things the library leaves to the application: the organisation a
token acts in (carried from the consent screen to every token through
``Connection``), a narrower set of grant types, and http redirects for
loopback addresses only.
"""
from urllib.parse import urlsplit

from oauth2_provider.oauth2_validators import OAuth2Validator

from .access import connection_usable
from .models import ConnectionCredential

ALLOWED_GRANT_TYPES = ('authorization_code', 'refresh_token')
LOOPBACK_HOSTS = ('127.0.0.1', '::1', 'localhost')


def _connection_for(**lookup):
    credential = (
        ConnectionCredential.objects
        .select_related('connection', 'connection__user', 'connection__organization')
        .filter(**lookup)
        .first()
    )
    return credential.connection if credential else None


class ApiOAuth2Validator(OAuth2Validator):

    # ── What may be asked for ────────────────────────────────────────────────

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        if grant_type not in ALLOWED_GRANT_TYPES:
            return False
        return super().validate_grant_type(client_id, grant_type, client, request, *args, **kwargs)

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        parts = urlsplit(redirect_uri or '')
        if parts.scheme == 'http' and parts.hostname not in LOOPBACK_HOSTS:
            return False
        return super().validate_redirect_uri(client_id, redirect_uri, request, *args, **kwargs)

    # ── Carrying the organisation from consent to every token ────────────────

    def _create_authorization_code(self, request, code, expires=None):
        grant = super()._create_authorization_code(request, code, expires)
        # Set by ConsentView from the organisation the user picked.
        connection = getattr(request, 'api_connection', None)
        if connection is not None:
            ConnectionCredential.objects.create(connection=connection, grant=grant)
        return grant

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        if not super().validate_code(client_id, code, client, request, *args, **kwargs):
            return False
        connection = _connection_for(grant__code=code, grant__application=client)
        if not connection_usable(connection):
            return False
        request.api_connection = connection
        return True

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        if not super().validate_refresh_token(refresh_token, client, request, *args, **kwargs):
            return False
        connection = _connection_for(refresh_token=request.refresh_token_instance)
        if not connection_usable(connection):
            return False
        request.api_connection = connection
        return True

    def _create_access_token(self, expires, request, token, source_refresh_token=None):
        access_token = super()._create_access_token(expires, request, token, source_refresh_token)
        self._bind(request, access_token=access_token)
        return access_token

    def _create_refresh_token(self, request, refresh_token_code, access_token, previous_refresh_token):
        refresh_token = super()._create_refresh_token(
            request, refresh_token_code, access_token, previous_refresh_token
        )
        self._bind(request, refresh_token=refresh_token)
        return refresh_token

    @staticmethod
    def _bind(request, **token):
        connection = getattr(request, 'api_connection', None)
        # A token with no connection has no organisation and is refused by the API.
        if connection is not None:
            ConnectionCredential.objects.create(connection=connection, **token)
