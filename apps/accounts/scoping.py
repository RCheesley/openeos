"""Helpers that keep every request inside the user's organisation and team."""
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import UserProfile


def get_user_org(user):
    try:
        return user.profile.organization
    except (UserProfile.DoesNotExist, AttributeError):
        return None


def get_active_team(request):
    """Return the session-pinned team if valid, else the user's first team."""
    try:
        user_teams = request.user.profile.teams.all()
    except AttributeError:
        return None
    if not user_teams.exists():
        return None
    stored_id = request.session.get('active_team_id')
    if stored_id:
        team = user_teams.filter(pk=stored_id).first()
        if team:
            return team
    team = user_teams.first()
    request.session['active_team_id'] = team.pk
    return team


def get_org_object_or_404(request, model, org_lookup='team__organization', **kwargs):
    """Like get_object_or_404, but only for records in the user's organisation."""
    org = get_user_org(request.user)
    if org is None:
        raise Http404
    return get_object_or_404(model, **{org_lookup: org}, **kwargs)


class OrgScopedMixin:
    """Limit a single-object generic view to records in the user's organisation.

    ``org_lookup`` is the ORM path from the view's model to its Organization.
    """

    org_lookup = 'team__organization'

    def get_queryset(self):
        queryset = super().get_queryset()
        org = get_user_org(self.request.user)
        if org is None:
            return queryset.none()
        return queryset.filter(**{self.org_lookup: org})
