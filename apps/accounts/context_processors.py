from .models import Team


def active_team(request):
    """Inject active_team and user_teams into every template context."""
    if not request.user.is_authenticated:
        return {}

    try:
        user_teams = list(request.user.profile.teams.select_related('organization').order_by('name'))
    except AttributeError:
        user_teams = []

    if not user_teams:
        return {'active_team': None, 'user_teams': []}

    # Resolve active team from session
    stored_id = request.session.get('active_team_id')
    team_map = {t.pk: t for t in user_teams}

    if stored_id and stored_id in team_map:
        current = team_map[stored_id]
    else:
        current = user_teams[0]
        request.session['active_team_id'] = current.pk

    return {'active_team': current, 'user_teams': user_teams}
