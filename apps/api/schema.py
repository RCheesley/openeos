"""How the OpenAPI document describes sign-in and errors."""
from drf_spectacular.contrib.django_oauth_toolkit import DjangoOAuthToolkitScheme
from drf_spectacular.openapi import AutoSchema

from .exceptions import PROBLEM_CONTENT_TYPE
from .serializers import ProblemSerializer

ERROR_RESPONSES = {
    '400': 'A query parameter was not valid.',
    '401': 'No access token, or one that is expired, revoked or issued for another address.',
    '403': 'The token lacks the scope this endpoint needs.',
    '404': 'No such record, or not one the caller may see.',
    '429': 'Too many requests.',
}


class ApiAutoSchema(AutoSchema):
    """Adds the problem-details error responses every endpoint shares."""

    def _get_response_bodies(self, direction='response'):
        bodies = super()._get_response_bodies(direction)
        if direction != 'response':
            return bodies
        has_id = '{' in self.path
        is_list = self._is_list_view()
        for code, description in ERROR_RESPONSES.items():
            if (code == '404' and not has_id) or (code == '400' and not is_list):
                continue
            response = self._get_response_for_code(ProblemSerializer, code, [PROBLEM_CONTENT_TYPE])
            response['description'] = description
            bodies.setdefault(code, response)
        return bodies


class ApiTokenScheme(DjangoOAuthToolkitScheme):
    target_class = 'apps.api.authentication.ApiTokenAuthentication'
    name = 'oauth2'
    priority = 1


def add_oauth2_metadata_url(result, generator, request, public):
    """Point clients at the RFC 8414 metadata (a field OpenAPI gained in 3.2)."""
    scheme = result.get('components', {}).get('securitySchemes', {}).get('oauth2')
    if scheme is not None and result.get('openapi', '').startswith('3.2'):
        scheme['oauth2MetadataUrl'] = '/.well-known/oauth-authorization-server'
    return result
