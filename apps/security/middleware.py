import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.audit.services import record

SESSION_LAST_ACTIVITY = 'last_activity'
# The session row is rewritten at most this often, so browsing does not turn
# every page view into a database write.
ACTIVITY_GRAIN_SECONDS = 60
KEEPALIVE_MIN_SECONDS = 30
KEEPALIVE_MAX_SECONDS = 300


def idle_timeout_seconds():
    return max(0, settings.SESSION_IDLE_TIMEOUT_MINUTES) * 60


def keepalive_interval_seconds():
    """How often a page that is in use without navigating should report in; 0 when not needed."""
    timeout = idle_timeout_seconds()
    if not timeout:
        return 0
    return max(KEEPALIVE_MIN_SECONDS, min(KEEPALIVE_MAX_SECONDS, timeout // 3))


class IdleSessionTimeoutMiddleware:
    """Sign a user out after ``SESSION_IDLE_TIMEOUT_MINUTES`` without a request.

    Any request by a signed-in user counts as activity unless the view sets
    ``request.counts_as_activity = False``. Must sit after the authentication
    and message middleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timeout = idle_timeout_seconds()
        if not timeout or not request.user.is_authenticated:
            return self.get_response(request)

        now = time.time()
        grain = min(ACTIVITY_GRAIN_SECONDS, timeout)
        last = request.session.get(SESSION_LAST_ACTIVITY)
        # The stored time can trail the true last request by up to the grain,
        # so allow that much extra and never expire a session early.
        if last is not None and now - last > timeout + grain:
            return self._expire(request)

        response = self.get_response(request)
        if (
            request.user.is_authenticated
            and getattr(request, 'counts_as_activity', True)
            and (last is None or now - last >= grain)
        ):
            request.session[SESSION_LAST_ACTIVITY] = now
        return response

    def _expire(self, request):
        record('user.session_expired', request=request, details={
            'idle_minutes': settings.SESSION_IDLE_TIMEOUT_MINUTES,
        })
        request.session.flush()
        request.user = AnonymousUser()
        if request.path in (reverse('login'), reverse('logout')):
            return self.get_response(request)
        messages.info(
            request, 'You were signed out after a period without activity. Sign in to carry on.',
        )
        return redirect_to_login(self._return_address(request))

    @staticmethod
    def _return_address(request):
        """Where to go after signing in again: this page, or the page a form was sent from."""
        if request.method in ('GET', 'HEAD'):
            return request.get_full_path()
        referer = request.META.get('HTTP_REFERER', '')
        if url_has_allowed_host_and_scheme(
            referer, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            parts = urlsplit(referer)
            return parts.path + (f'?{parts.query}' if parts.query else '')
        return settings.LOGIN_REDIRECT_URL
