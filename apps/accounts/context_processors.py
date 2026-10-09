from .branding import brand_for
from .scoping import get_active_org, get_active_team, get_user_orgs, is_org_admin


def active_context(request):
    """Inject the active organisation and team, and the switcher choices, into templates."""
    if not request.user.is_authenticated:
        return {}
    org = get_active_org(request)
    team = get_active_team(request)
    user_teams = []
    if org is not None:
        user_teams = list(request.user.profile.teams.filter(organization=org).order_by('name'))
    host_org = getattr(request, 'host_org', None)
    if host_org is not None:
        user_orgs = [host_org]
    else:
        user_orgs = list(get_user_orgs(request.user).order_by('name'))
    return {
        'active_org': org,
        'user_orgs': user_orgs,
        'active_team': team,
        'user_teams': user_teams,
        'is_active_org_admin': is_org_admin(request.user, org),
    }


def branding(request):
    """Brand for the host's organisation, else the user's active one, else the default.

    Unlike ``active_context`` this also applies to anonymous requests, so the
    login page on an organisation's own domain carries its branding.
    """
    org = getattr(request, 'host_org', None)
    if org is None and request.user.is_authenticated:
        org = get_active_org(request)
    return {'brand': brand_for(org)}
