"""Erase one person from the instance without tearing holes in its history.

The account row stays, emptied and switched off, because Priorities, Actions
and metrics must have an owner and meetings keep one row per participant.
Everything that identifies the person goes: their name, email and username,
avatar, two-factor devices, sessions, memberships and site-wide rights.
Records that name them are pointed at one shared, switched-off account called
"Former member", so the organisation still sees that somebody did the work
but not who, and can no longer tell which records belonged to the same
person. Text the person wrote (notes, comments, check-ins) is the
organisation's record and stays as written.

:func:`plan` reads and changes nothing; :func:`erase` does the work in one
transaction. Running :func:`erase` again on an erased account finds nothing
left to change. The decision for each relation lives in
:mod:`apps.accounts.personal_data.relations`.
"""
import re
from collections import OrderedDict
from dataclasses import dataclass, field as dataclass_field

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.db.models import Q

from apps.accounts.models import Membership, UserProfile
from apps.audit.models import AuditEvent
from apps.audit.services import record
from apps.notifications.models import NotificationPreference

from .relations import ERASE_DELETE, ERASE_KEEP, ERASE_REASSIGN, handled

PLACEHOLDER_USERNAME = 'former-member'
PLACEHOLDER_FIRST_NAME = 'Former'
PLACEHOLDER_LAST_NAME = 'member'
PLACEHOLDER_LABEL = f'{PLACEHOLDER_FIRST_NAME} {PLACEHOLDER_LAST_NAME}'
ERASED_USERNAME = 'erased-{pk}'

LAST_ADMIN = 'last_admin'
SUPERUSER = 'superuser'
PLACEHOLDER = 'placeholder'

USER_TARGET = 'auth.user'

# Every column of the account, the profile and the notification preferences is
# either cleared by the erasure or named here as kept, and a test compares
# these with the models, so a new column (a phone number, a job title) cannot
# be added without deciding which it is.
ACCOUNT_FIELDS_KEPT = ('id', 'date_joined')
PROFILE_FIELDS_CLEARED = ('avatar', 'teams')
PROFILE_FIELDS_KEPT = ('id', 'user', 'created_at', 'updated_at')
PREFERENCE_FIELDS_KEPT = ('id', 'user')

# A value in an audit event's details is treated as naming a person only when
# its key says so; a username such as "admin" must not rewrite {"role": "admin"}.
PERSON_KEY_HINTS = ('user', 'name', 'email', 'member', 'owner', 'actor', 'login', 'person')

# Columns cleared on the audit events the person caused.
AUDIT_ACTOR_SCRUB = {'actor_label': PLACEHOLDER_LABEL, 'ip_address': None, 'user_agent': ''}


class ErasureRefused(Exception):
    """Raised by :func:`erase` when a safeguard applies and its flag was not given."""

    def __init__(self, refusals):
        self.refusals = refusals
        super().__init__(' '.join(message for _, message in refusals))


class PlaceholderConflict(Exception):
    """A real account already uses the placeholder's username."""


@dataclass
class Step:
    action: str          # 'blank', 'delete', 'reassign', 'keep', 'file'
    what: str
    count: int
    key: str = ''

    @property
    def changes(self):
        return self.action != ERASE_KEEP and self.count > 0


@dataclass
class Plan:
    steps: list = dataclass_field(default_factory=list)
    refusals: list = dataclass_field(default_factory=list)

    @property
    def has_changes(self):
        return any(step.changes for step in self.steps)

    def counts(self):
        """``{key: count}`` of what changes, with no personal data in it."""
        return OrderedDict((s.key, s.count) for s in self.steps if s.changes and s.key)


# ── the two special accounts ───────────────────────────────────────────────

def erased_username(user):
    return ERASED_USERNAME.format(pk=user.pk)


def is_erased(user):
    return (
        user.get_username() == erased_username(user)
        and not user.is_active and not user.has_usable_password() and not user.email
    )


def is_placeholder(user):
    return (
        user.get_username() == PLACEHOLDER_USERNAME
        and not user.is_active and not user.has_usable_password()
    )


def get_placeholder(create=False):
    """The shared "Former member" account, made the first time it is needed.

    It is switched off, has no password, email or membership, and so never
    appears in a member list or an owner picker and cannot sign in.
    """
    user_model = get_user_model()
    existing = user_model._default_manager.filter(username=PLACEHOLDER_USERNAME).first()
    if existing is not None:
        if not is_placeholder(existing):
            raise PlaceholderConflict(
                f'An account with the username "{PLACEHOLDER_USERNAME}" already exists and '
                f'can sign in. Rename it, then run the erasure again.'
            )
        return existing
    if not create:
        return None
    placeholder = user_model(
        username=PLACEHOLDER_USERNAME, first_name=PLACEHOLDER_FIRST_NAME,
        last_name=PLACEHOLDER_LAST_NAME, email='', is_active=False,
    )
    placeholder.set_unusable_password()
    placeholder.save()
    _switch_off_notifications(placeholder)
    return placeholder


# ── safeguards ─────────────────────────────────────────────────────────────

def refusals(user):
    """``[(code, message), ...]`` for each safeguard that applies to ``user``."""
    found = []
    if user.get_username() == PLACEHOLDER_USERNAME:
        found.append((PLACEHOLDER, f'"{PLACEHOLDER_USERNAME}" is the placeholder account.'))
    if user.is_superuser:
        found.append((SUPERUSER, 'This account is a superuser.'))
    admin_of = Membership.objects.filter(
        user=user, role=Membership.ROLE_ADMIN
    ).select_related('organization')
    for membership in admin_of:
        others = Membership.objects.filter(
            organization=membership.organization, role=Membership.ROLE_ADMIN,
            user__is_active=True,
        ).exclude(user=user)
        if not others.exists():
            found.append((
                LAST_ADMIN,
                f'This account is the only admin of "{membership.organization.name}".',
            ))
    return found


def _blocking(found, allow_last_admin, allow_superuser):
    allowed = set()
    if allow_last_admin:
        allowed.add(LAST_ADMIN)
    if allow_superuser:
        allowed.add(SUPERUSER)
    return [(code, message) for code, message in found if code not in allowed]


# ── the plan ───────────────────────────────────────────────────────────────

def _account_target(user):
    return OrderedDict([
        ('username', erased_username(user)),
        ('first_name', PLACEHOLDER_FIRST_NAME),
        ('last_name', PLACEHOLDER_LAST_NAME),
        ('email', ''),
        ('is_active', False),
        ('is_staff', False),
        ('is_superuser', False),
        ('last_login', None),
    ])


def _account_changes(user):
    names = [name for name, value in _account_target(user).items() if getattr(user, name) != value]
    if user.has_usable_password():
        names.append('password')
    return names


def _boolean_preferences():
    return [
        f.name for f in NotificationPreference._meta.concrete_fields
        if isinstance(f, models.BooleanField)
    ]


def _switch_off_notifications(user):
    return NotificationPreference.objects.filter(user=user).update(
        **{name: False for name in _boolean_preferences()}
    )


def _sessions_of(user):
    """Keys of the stored sessions signed in as ``user``."""
    wanted = str(user.pk)
    keys = []
    for session in Session.objects.iterator():
        if str(session.get_decoded().get('_auth_user_id')) == wanted:
            keys.append(session.session_key)
    return keys


def _identifiers(user):
    """The strings that name the person in free-form audit data."""
    return {
        'email': (user.email or '').strip(),
        'username': user.get_username().strip(),
        'full_name': user.get_full_name().strip(),
    }


def _own_targets(user):
    """``Q`` for audit events recorded about the person's own rows."""
    query = Q(target_type=USER_TARGET, target_id=str(user.pk))
    membership_pks = [
        str(pk) for pk in Membership.objects.filter(user=user).values_list('pk', flat=True)
    ]
    if membership_pks:
        query |= Q(target_type='accounts.membership', target_id__in=membership_pks)
    for model in (UserProfile, NotificationPreference):
        pks = [str(pk) for pk in model.objects.filter(user=user).values_list('pk', flat=True)]
        if pks:
            meta = model._meta
            query |= Q(target_type=f'{meta.app_label}.{meta.model_name}', target_id__in=pks)
    return query


def _scrub_text(text, identifiers, whole_value):
    """``text`` with the person's email cut out, and replaced outright if it is their name."""
    email = identifiers.get('email')
    if email:
        text = re.sub(re.escape(email), PLACEHOLDER_LABEL, text, flags=re.IGNORECASE)
    if whole_value:
        names = {identifiers.get('username', '').lower(), identifiers.get('full_name', '').lower()}
        names.discard('')
        if text.strip().lower() in names:
            return PLACEHOLDER_LABEL
    return text


def _scrub_details(value, identifiers, key=''):
    if isinstance(value, dict):
        return {k: _scrub_details(v, identifiers, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_details(v, identifiers, key) for v in value]
    if isinstance(value, str):
        named = any(hint in key.lower() for hint in PERSON_KEY_HINTS)
        return _scrub_text(value, identifiers, whole_value=named)
    return value


def _audit_mentions(user):
    """``[(event, new target_label, new details), ...]`` for events that name the person.

    These are events somebody else caused, or nobody did (a failed sign-in):
    events about the person's account, membership or profile, and events
    whose details hold their email, or their username or name under a key
    that says it is a person.
    """
    if is_erased(user):
        # Nothing names an erased account any more; events recorded about it
        # since (the erasure itself) carry only its placeholder username.
        return []
    identifiers = _identifiers(user)
    own = _own_targets(user)
    query = own
    for value in identifiers.values():
        if value:
            query |= Q(details__icontains=value) | Q(target_label__icontains=value)
    own_pks = set(AuditEvent.objects.filter(own).values_list('pk', flat=True))
    found = []
    for event in AuditEvent.objects.filter(query).distinct():
        if event.pk in own_pks:
            label = PLACEHOLDER_LABEL
        else:
            label = _scrub_text(event.target_label, identifiers, whole_value=True)
        details = _scrub_details(event.details, identifiers)
        if label != event.target_label or details != event.details:
            found.append((event, label, details))
    return found


def plan(user):
    """What :func:`erase` would do to ``user``, without changing anything."""
    steps = []
    account = _account_changes(user)
    steps.append(Step(
        'blank', 'Account fields replaced or cleared: ' + (', '.join(account) or 'none'),
        len(account), 'account_fields',
    ))

    profile = UserProfile.objects.filter(user=user).first()
    if profile is not None:
        avatar = profile.avatar.name if profile.avatar else ''
        steps.append(Step(
            'file', f'Avatar file removed: {avatar or "none"}', 1 if avatar else 0, 'avatar',
        ))
        steps.append(Step(
            ERASE_DELETE, 'Team memberships removed', profile.teams.count(), 'team_memberships',
        ))
    preferences_on = sum(
        NotificationPreference.objects.filter(user=user, **{name: True}).count()
        for name in _boolean_preferences()
    )
    steps.append(Step(
        'blank', 'Notification preferences switched off', preferences_on,
        'notification_preferences',
    ))
    steps.append(Step(ERASE_DELETE, 'Sign-in sessions ended', len(_sessions_of(user)), 'sessions'))

    for key, model, field, handling in handled():
        count = model._default_manager.filter(**{field.name: user}).count()
        name = f'{model._meta.verbose_name_plural} ({field.name})'
        if handling.erase == ERASE_REASSIGN:
            what = f'{name}: shown as "{PLACEHOLDER_LABEL}"'
        elif handling.erase == ERASE_DELETE:
            what = f'{name}: deleted'
        else:
            what = f'{name}: kept on the anonymised account'
        steps.append(Step(handling.erase, what, count, key))

    steps.append(Step(
        'blank', 'Audit events about the person: name and email removed',
        len(_audit_mentions(user)), 'audit_mentions',
    ))
    return Plan(steps=steps, refusals=refusals(user))


# ── the erasure ────────────────────────────────────────────────────────────

def erase(user, *, allow_last_admin=False, allow_superuser=False, via='command'):
    """Erase ``user`` and return the :class:`Plan` that was carried out.

    Raises :class:`ErasureRefused` when a safeguard applies and its flag was
    not given. An account that is already erased comes back with a plan that
    has no changes, and nothing is written, not even an audit event.
    """
    avatar_name = ''
    with transaction.atomic():
        user = get_user_model()._default_manager.select_for_update().get(pk=user.pk)
        carried_out = plan(user)
        blocking = _blocking(carried_out.refusals, allow_last_admin, allow_superuser)
        if blocking:
            raise ErasureRefused(blocking)
        if not carried_out.has_changes:
            return carried_out

        placeholder = get_placeholder(create=True)
        organizations = [
            m.organization for m in
            Membership.objects.filter(user=user).select_related('organization')
        ]

        # While the name, email and membership ids are still there to look for.
        for event, label, details in _audit_mentions(user):
            event.target_label = label
            event.details = details
            event.save(update_fields=['target_label', 'details'])

        profile = UserProfile.objects.filter(user=user).first()
        if profile is not None:
            avatar_name = profile.avatar.name if profile.avatar else ''
            profile.teams.clear()
            profile.avatar = None
            profile.save()
        _switch_off_notifications(user)
        Session.objects.filter(session_key__in=_sessions_of(user)).delete()

        for key, model, field, handling in handled():
            rows = model._default_manager.filter(**{field.name: user})
            if handling.erase == ERASE_REASSIGN:
                extra = AUDIT_ACTOR_SCRUB if model is AuditEvent else {}
                rows.update(**{field.name: placeholder}, **extra)
            elif handling.erase == ERASE_DELETE:
                rows.delete()

        for name, value in _account_target(user).items():
            setattr(user, name, value)
        user.set_unusable_password()
        user.save()

        details = {'via': via, 'changed': carried_out.counts()}
        record('user.erased', target=user, details=details)
        for organization in organizations:
            record('user.erased', organization=organization, target=user, details={'via': via})

    # Outside the transaction: a file cannot be rolled back, so it goes last.
    if avatar_name and default_storage.exists(avatar_name):
        default_storage.delete(avatar_name)
    return carried_out
