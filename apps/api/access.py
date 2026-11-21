"""The one place that decides whether a connection may still be used.

Checked when a token is presented and again when one is refreshed, so removing
a user from an organisation, switching the API off or revoking the connection
takes effect on the next request.
"""
from apps.accounts.scoping import get_user_orgs

from .models import OrganizationApiAccess


def api_organizations(user, host_org=None):
    """Organisations ``user`` may connect an application to.

    Membership decides, as it does on the web, and the organisation must have
    the API switched on. On an organisation's own hostname only that
    organisation is offered.
    """
    orgs = OrganizationApiAccess.enabled_organizations(get_user_orgs(user))
    if host_org is not None:
        orgs = orgs.filter(pk=host_org.pk)
    return orgs


def connection_usable(connection, host_org=None):
    if connection is None or not connection.is_active:
        return False
    if not connection.user.is_active:
        return False
    return api_organizations(connection.user, host_org).filter(pk=connection.organization_id).exists()
