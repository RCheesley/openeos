"""Pin a request to the organisation that owns its hostname.

Each organisation may register one or more hostnames (OrganizationDomain). When
a request arrives on one of them, ``request.host_org`` is that organisation and
the rest of the app treats it as the active one regardless of the session. On
an unmapped host both attributes are None and the session switcher applies.
"""
from django.core.exceptions import DisallowedHost, PermissionDenied

from .models import Membership, OrganizationDomain

# Paths a non-member may still reach on a pinned host, so they can log in,
# reset a password, log out, use the Django admin or answer a health check.
OPEN_PATH_PREFIXES = ('/accounts/', '/admin/', '/healthz/')


def request_hostname(request):
    try:
        host = request.get_host()
    except DisallowedHost:
        return None
    return host.split(':')[0].lower()


class OrganizationDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.org_domain = self.resolve(request_hostname(request))
        request.host_org = request.org_domain.organization if request.org_domain else None
        if request.host_org is not None and self.is_locked_out(request):
            raise PermissionDenied('You do not have access to this organisation.')
        return self.get_response(request)

    @staticmethod
    def resolve(hostname):
        if not hostname:
            return None
        return (
            OrganizationDomain.objects
            .select_related('organization')
            .filter(hostname=OrganizationDomain.normalize(hostname))
            .first()
        )

    @staticmethod
    def is_locked_out(request):
        user = request.user
        if not user.is_authenticated or user.is_superuser:
            return False
        if request.path.startswith(OPEN_PATH_PREFIXES):
            return False
        return not Membership.objects.filter(user=user, organization=request.host_org).exists()
