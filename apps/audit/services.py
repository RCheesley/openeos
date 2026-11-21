"""Write audit events.

Other features call :func:`record` and carry on; a failed audit write is logged
but never raised, so the audit log cannot break the action it describes.
"""
import ipaddress
import logging
from typing import NamedTuple

from django.db import models

from .models import AuditEvent

logger = logging.getLogger(__name__)

USER_AGENT_MAX_LENGTH = AuditEvent._meta.get_field('user_agent').max_length
ACTOR_LABEL_MAX_LENGTH = AuditEvent._meta.get_field('actor_label').max_length
TARGET_LABEL_MAX_LENGTH = AuditEvent._meta.get_field('target_label').max_length


class TargetSnapshot(NamedTuple):
    """What :func:`record` stores about a target, taken while the row still exists."""

    type: str
    id: str
    label: str


def snapshot(instance):
    """Describe ``instance`` now, so it can be passed as ``target`` after it is deleted.

    A deleted instance has no primary key any more, and its ``str()`` may follow
    relations that are gone, so a deletion takes the snapshot first and records
    the event once the delete has succeeded.
    """
    meta = instance._meta
    return TargetSnapshot(
        f'{meta.app_label}.{meta.model_name}', str(instance.pk),
        str(instance)[:TARGET_LABEL_MAX_LENGTH],
    )


def deletion_details(title, team=None, **extra):
    """The details every ``*.deleted`` event carries: the title and team at the time."""
    details = {'title': title}
    if team is not None:
        details['team_id'] = team.pk
        details['team'] = team.name
    details.update(extra)
    return details


def record_for_user(action, user, *, request=None, details=None):
    """Record a change to ``user``'s own account in every organisation they belong to.

    A password or two-factor change affects each of those organisations
    equally, so each one's admins see it. A user in no organisation gets a
    single unattributed event, visible in the Django admin only.
    """
    try:
        from apps.accounts.models import Organization
        organizations = list(Organization.objects.filter(memberships__user=user)) or [None]
    except Exception:  # noqa: BLE001 (an audit failure must not break the caller)
        logger.exception('Could not look up organisations for audit event %r', action)
        return []
    return [
        record(
            action, request=request, actor=user, organization=organization,
            target=user, details=details,
        )
        for organization in organizations
    ]


def record(action, *, request=None, actor=None, organization=None, target=None, details=None):
    """Create and return an :class:`AuditEvent`, or ``None`` if writing it failed.

    ``action`` is a dotted lower-case name such as ``user.login``. When ``request``
    is given, the actor (if authenticated), IP address and user agent are taken
    from it; an explicit ``actor`` always wins. ``target`` may be any model
    instance and is stored as ``app_label.model_name``, its pk and ``str()``;
    for a deleted row pass the :func:`snapshot` taken beforehand.
    """
    try:
        return _record(action, request, actor, organization, target, details)
    except Exception:  # noqa: BLE001 — an audit failure must not break the caller
        logger.exception('Could not record audit event %r', action)
        return None


def _record(action, request, actor, organization, target, details):
    if actor is None and request is not None:
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            actor = user

    fields = {
        'action': action,
        'actor': actor,
        'actor_label': actor.get_username()[:ACTOR_LABEL_MAX_LENGTH] if actor else '',
        'organization': organization,
        'details': details or {},
    }
    if request is not None:
        fields['ip_address'] = client_ip(request)
        fields['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:USER_AGENT_MAX_LENGTH]
    if isinstance(target, models.Model):
        target = snapshot(target)
    if isinstance(target, TargetSnapshot):
        fields['target_type'], fields['target_id'], fields['target_label'] = target
    return AuditEvent.objects.create(**fields)


def client_ip(request):
    """Return the client's IP address, honouring the first X-Forwarded-For value."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    raw = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None
