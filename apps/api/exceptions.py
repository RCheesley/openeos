"""Every API error as RFC 9457 problem details, in one shape."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import set_rollback

PROBLEM_CONTENT_TYPE = 'application/problem+json'

TITLES = {
    400: 'Bad request',
    401: 'Authentication required',
    403: 'Forbidden',
    404: 'Not found',
    405: 'Method not allowed',
    406: 'Not acceptable',
    415: 'Unsupported media type',
    429: 'Too many requests',
}


def problem(status_code, detail=None, headers=None, **extra):
    body = {'type': 'about:blank', 'title': TITLES.get(status_code, 'Error'), 'status': status_code}
    if detail:
        body['detail'] = detail
    body.update(extra)
    return Response(body, status=status_code, headers=headers, content_type=PROBLEM_CONTENT_TYPE)


def problem_details_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    if not isinstance(exc, exceptions.APIException):
        return None  # not an API error but a fault in the server: let Django report it

    headers = {}
    if getattr(exc, 'auth_header', None):
        headers['WWW-Authenticate'] = exc.auth_header
    if getattr(exc, 'wait', None):
        headers['Retry-After'] = '%d' % exc.wait

    set_rollback()
    if isinstance(exc, exceptions.ValidationError):
        errors = exc.detail if isinstance(exc.detail, dict) else {'request': exc.detail}
        return problem(exc.status_code, 'One or more parameters are not valid.', headers, errors=errors)
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        # One answer for "does not exist" and "not yours to see".
        return problem(404, 'Nothing here, or nothing you may see.', headers)
    detail = exc.detail if isinstance(exc.detail, str) else None
    if isinstance(exc.detail, dict):
        detail = str(exc.detail.get('detail', '')) or None
    return problem(exc.status_code, detail and str(detail), headers)
