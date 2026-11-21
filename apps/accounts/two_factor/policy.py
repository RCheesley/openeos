"""An organisation's rule that everyone in it signs in with a second step."""
from django.db.models import Exists, OuterRef
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import Organization


def requires_two_factor(org):
    return org is not None and org.require_two_factor


def organizations_requiring_two_factor(user):
    """The organisations ``user`` belongs to that require two-factor authentication."""
    return Organization.objects.filter(memberships__user=user, require_two_factor=True)


def with_two_factor_status(memberships):
    """Annotate memberships with ``has_two_factor``: the person has a confirmed authenticator."""
    return memberships.annotate(has_two_factor=Exists(
        TOTPDevice.objects.filter(user=OuterRef('user'), confirmed=True)
    ))


def record_two_factor_requirement(org, *, request):
    """Note in the audit log that ``org`` has just started or stopped requiring it."""
    from apps.audit.services import record

    action = (
        'organization.two_factor_required' if org.require_two_factor
        else 'organization.two_factor_not_required'
    )
    record(action, request=request, organization=org, target=org)
