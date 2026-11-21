from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import Resolver404, resolve, reverse

from apps.accounts.scoping import get_active_org

from . import get_totp_device
from .policy import requires_two_factor

TWO_FACTOR_PREFIX = '/accounts/2fa/'


class TwoFactorRequiredMiddleware:
    """Hold a signed-in user at the second step until it is done.

    A user who has enrolled an authenticator goes to the verify page until they
    use it. A user who has not, working in an organisation that requires
    two-factor authentication, goes to the set-up page instead; the organisation
    is the active one (see ``scoping.get_active_org``), so the host an
    organisation owns and the session switcher are both honoured, and the same
    person is left alone in another organisation that does not require it.

    Must sit after ``django_otp.middleware.OTPMiddleware`` so ``request.user.is_verified``
    is available, and after ``OrganizationDomainMiddleware`` so ``request.host_org`` is.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        step = self._pending_step(request)
        if step:
            return redirect_to_login(request.get_full_path(), login_url=reverse(step))
        return self.get_response(request)

    def _pending_step(self, request):
        """The URL name of the page this request must go to first, or None."""
        user = request.user
        if not user.is_authenticated or user.is_verified():
            return None
        if self._is_exempt(request.path):
            return None
        if get_totp_device(user) is not None:
            return 'accounts:two_factor_verify'
        if self._is_exempt_from_setup(request.path):
            return None
        if requires_two_factor(get_active_org(request)):
            return 'accounts:two_factor_setup'
        return None

    @staticmethod
    def _is_exempt(path):
        # The 2FA prefix covers verify, setup, disable and backup codes; setup guards
        # itself against unverified re-enrolment.
        prefixes = [
            TWO_FACTOR_PREFIX,
            reverse('logout'),
            reverse('admin:login'),
            settings.STATIC_URL,
            settings.MEDIA_URL,
            '/healthz/',
        ]
        return any(path.startswith(prefix) for prefix in prefixes)

    @staticmethod
    def _is_exempt_from_setup(path):
        """Pages a person may still use before setting up a factor their organisation requires.

        Their own profile, and the organisation switcher so that someone who
        also belongs to an organisation without the requirement can go and
        work there.
        """
        if path.startswith(reverse('accounts:profile')):
            return True
        match = resolve_or_none(path)
        return match is not None and match.view_name == 'accounts:org_switch'


def resolve_or_none(path):
    try:
        return resolve(path)
    except Resolver404:
        return None
