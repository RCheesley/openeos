"""Managing who belongs to an organisation: roles, handing records over, removal.

Everything here is limited to one organisation. A user may belong to several,
so removing a member ends their place in this organisation and never touches
the account or what they own elsewhere.
"""
from django.db import transaction

from apps.accountability.models import AccountabilityNode
from apps.issues.models import Issue
from apps.rocks.models import Rock
from apps.scorecards.models import ScorecardMetric
from apps.todos.models import ToDo

from .models import Membership, Team

KIND_ROCKS = 'rocks'
KIND_TODOS = 'todos'
KIND_METRICS = 'metrics'
KIND_SEATS = 'seats'

# Records that cannot be left without an owner, so removal always hands them on.
REQUIRED_KINDS = (KIND_ROCKS, KIND_TODOS, KIND_METRICS)
ALL_KINDS = REQUIRED_KINDS + (KIND_SEATS,)


class LastAdminError(Exception):
    """The change would leave the organisation with no admin."""


def owned_records(user, org):
    """What ``user`` still owns in ``org`` and would hand on, as ``{kind: queryset}``.

    Only live records are listed: open Rocks and To-Dos, active metrics and
    seats on the chart. Completed or dropped Rocks, completed To-Dos and
    inactive metrics keep their owner as a record of who did the work.
    """
    return {
        KIND_ROCKS: Rock.objects.filter(
            owner=user, team__organization=org,
            status__in=[Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK],
        ),
        KIND_TODOS: ToDo.objects.filter(
            owner=user, team__organization=org, status=ToDo.STATUS_OPEN,
        ),
        KIND_METRICS: ScorecardMetric.objects.filter(
            owner=user, scorecard__team__organization=org, is_active=True,
        ),
        KIND_SEATS: AccountabilityNode.objects.filter(owner=user, organization=org),
    }


def open_issues_raised(user, org):
    """Open Issues ``user`` raised in ``org``. They stay with the team; nothing moves."""
    return Issue.objects.filter(
        created_by=user, originating_team__organization=org,
        status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS],
    )


def teams_missing(new_owner, user, org, kinds):
    """Teams whose Rocks or To-Dos would move to someone who is not in the team.

    The Rock and To-Do forms only offer a team's own members as owner, so a
    hand-over has to respect the same rule or the record could not be edited.
    """
    records = owned_records(user, org)
    team_ids = set()
    for kind in (KIND_ROCKS, KIND_TODOS):
        if kind in kinds:
            team_ids.update(records[kind].values_list('team_id', flat=True))
    return (
        Team.objects.filter(pk__in=team_ids)
        .exclude(members__user=new_owner)
        .order_by('name')
    )


def reassign_records(user, org, new_owner, kinds):
    """Move ``user``'s live records of the given kinds in ``org`` to ``new_owner``.

    Returns ``{kind: number moved}``. ``new_owner`` may be None only for seats,
    which then become vacant.
    """
    records = owned_records(user, org)
    with transaction.atomic():
        return {
            kind: records[kind].update(owner=new_owner)
            for kind in ALL_KINDS if kind in kinds
        }


def is_last_admin(membership):
    if membership.role != Membership.ROLE_ADMIN:
        return False
    return not (
        Membership.objects
        .filter(organization=membership.organization, role=Membership.ROLE_ADMIN)
        .exclude(pk=membership.pk)
        .exists()
    )


def _lock_admins(org):
    """Hold the organisation's admin rows so two changes cannot both remove the last admin."""
    list(
        Membership.objects.select_for_update()
        .filter(organization=org, role=Membership.ROLE_ADMIN)
        .values_list('pk', flat=True)
    )


def change_role(membership, role):
    """Set the member's role. Returns the previous role."""
    with transaction.atomic():
        _lock_admins(membership.organization)
        membership.refresh_from_db()
        previous = membership.role
        if role != Membership.ROLE_ADMIN and is_last_admin(membership):
            raise LastAdminError
        membership.role = role
        membership.save(update_fields=['role', 'updated_at'])
    return previous


def remove_member(membership, new_owner=None, vacate_seats=False):
    """End a membership: hand on live records, leave the organisation's teams, drop the membership.

    All of it happens in one transaction. The user account is kept. Returns
    ``{kind: number moved}``; seats left vacant are counted under ``'vacated'``.
    """
    user, org = membership.user, membership.organization
    with transaction.atomic():
        _lock_admins(org)
        membership.refresh_from_db()
        if is_last_admin(membership):
            raise LastAdminError
        records = owned_records(user, org)
        if new_owner is None and any(records[kind].exists() for kind in REQUIRED_KINDS):
            raise ValueError('Records that need an owner must be handed to another member.')
        moved = reassign_records(user, org, new_owner, REQUIRED_KINDS)
        if vacate_seats or new_owner is None:
            moved['vacated'] = records[KIND_SEATS].update(owner=None)
        else:
            moved.update(reassign_records(user, org, new_owner, [KIND_SEATS]))
        user.profile.teams.remove(*Team.objects.filter(organization=org, members__user=user))
        membership.delete()
    return moved
