"""Write one person's data into a zip archive they can read.

The archive is a copy for the person, not a backup: it cannot be imported.
It carries their account and profile, their memberships and teams, their
notification preferences, every record that names them in the organisations
they belong to, and the instance's logs of what they did. Which records name
a person is not listed here: it comes from
:mod:`apps.accounts.personal_data.relations`, which the registry test keeps
complete.

What never goes in: the password hash, two-factor secrets and backup codes,
sessions and tokens, and other people's names. A record keeps its own text
and the names of the things it belongs to (its team, its Priority, its
meeting) but every link to another account is left out.
"""
import zipfile
from collections import Counter, OrderedDict
from datetime import timezone as dt_timezone

from django.contrib.admin.models import LogEntry
from django.core.files.storage import default_storage
from django.db import models
from django.db.models import Q
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from apps.accounts.models import Membership, Team, UserProfile
from apps.accounts.portability.export import (
    USER_FIELDS, ArchiveTooLarge, _json, _organization_filter, _organization_paths, _put,
    label_for,
)
from apps.accounts.two_factor import backup_code_count, get_totp_device
from apps.audit.models import AuditEvent
from apps.notifications.models import NotificationPreference

from .relations import EXPORT_RECORD, handled

__all__ = ['ArchiveTooLarge', 'archive_filename', 'build_personal_archive']

FORMAT_VERSION = 1

USER_TARGET = 'auth.user'


def archive_filename(user, when):
    stamp = when.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%MZ')
    return f'empresadence-personal-data-{user.pk}-{stamp}.zip'


def build_personal_archive(user, *, fileobj, via='web', max_bytes=None, exported_at=None):
    """Write ``user``'s archive to ``fileobj`` and return the manifest.

    ``fileobj`` must be a seekable binary file open for writing. With
    ``max_bytes`` set, :class:`ArchiveTooLarge` is raised before any entry
    that would take the archive past the limit.
    """
    exported_at = exported_at or timezone.now()
    memberships = list(
        Membership.objects.filter(user=user).select_related('organization')
        .order_by('organization__name', 'pk')
    )
    organizations = [m.organization for m in memberships]
    record_counts = OrderedDict()
    elsewhere = OrderedDict()
    files = []

    archive = zipfile.ZipFile(fileobj, 'w', zipfile.ZIP_DEFLATED)
    try:
        _put(archive, 'account.json', _json(_account(user)), max_bytes)
        _put(archive, 'memberships.json', _json(_memberships(user, memberships)), max_bytes)

        paths = _organization_paths()
        for model, fields in _record_models():
            label = label_for(model)
            mine = model._default_manager.filter(_named_q(fields, user))
            seen = set()
            if model in paths:
                for org in organizations:
                    rows = list(
                        mine.filter(_organization_filter(model, org, paths))
                        .order_by('pk').distinct()
                    )
                    seen.update(row.pk for row in rows)
                    if not rows:
                        continue
                    name = f'organisations/{org.slug}/{label}.json'
                    payload = [_record(row, fields, user, org, paths[model][0]) for row in rows]
                    _put(archive, name, _json(payload), max_bytes)
                    record_counts[name] = len(payload)
                rest = mine.exclude(pk__in=seen)
                counted = Counter(
                    rest.values_list(f'{paths[model][0]}__name', flat=True)
                )
                for org_name, count in sorted(counted.items(), key=lambda kv: str(kv[0])):
                    elsewhere.setdefault(org_name or 'Unknown organisation', OrderedDict())[
                        label] = count
            else:
                rows = list(mine.order_by('pk'))
                if rows:
                    name = f'other/{label}.json'
                    payload = [_record(row, fields, user, None, '') for row in rows]
                    _put(archive, name, _json(payload), max_bytes)
                    record_counts[name] = len(payload)

        for name, payload in (
            ('activity/audit-log.json', _audit_events(user)),
            ('activity/admin-site-log.json', _admin_log(user)),
        ):
            _put(archive, name, _json(payload), max_bytes)
            record_counts[name] = len(payload)

        if elsewhere:
            _put(archive, 'former-organisations.json', _json(elsewhere), max_bytes)

        for name, content in _media_files(user):
            _put(archive, f'media/{name}', content, max_bytes)
            files.append(name)

        manifest = OrderedDict([
            ('format_version', FORMAT_VERSION),
            ('kind', 'personal-data'),
            ('exported_at', exported_at.astimezone(dt_timezone.utc).isoformat(timespec='seconds')),
            ('via', via),
            ('user', {'id': user.pk, 'username': user.get_username()}),
            ('organizations', [
                {'id': org.pk, 'name': org.name, 'slug': org.slug} for org in organizations
            ]),
            ('record_counts', record_counts),
            ('former_organizations', elsewhere),
            ('files', files),
        ])
        _put(archive, 'manifest.json', _json(manifest), max_bytes)
        _put(archive, 'README.txt', _readme(user, manifest), max_bytes)
    finally:
        archive.close()
    return manifest


# ── account.json and memberships.json ──────────────────────────────────────

def _account(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    preference = NotificationPreference.for_user(user)
    device = get_totp_device(user)
    return OrderedDict([
        ('account', OrderedDict(
            [(name, getattr(user, name)) for name in USER_FIELDS]
            + [
                ('is_staff', user.is_staff),
                ('is_superuser', user.is_superuser),
                ('groups', sorted(user.groups.values_list('name', flat=True))),
            ]
        )),
        ('profile', OrderedDict(
            (field.name, _plain(getattr(profile, field.attname)))
            for field in UserProfile._meta.concrete_fields
            if not field.is_relation and not field.primary_key
        )),
        ('two_factor', OrderedDict([
            ('enabled', device is not None),
            ('enabled_since', getattr(device, 'created_at', None)),
            ('last_used_at', getattr(device, 'last_used_at', None)),
            ('backup_codes_remaining', backup_code_count(user)),
        ])),
        ('notification_preferences', OrderedDict(
            (field.name, getattr(preference, field.name))
            for field in NotificationPreference._meta.concrete_fields
            if isinstance(field, models.BooleanField)
        )),
    ])


def _memberships(user, memberships):
    teams = list(
        Team.objects.filter(members__user=user).select_related('organization').order_by('name')
    )
    member_org_pks = {m.organization_id for m in memberships}
    return OrderedDict([
        ('memberships', [
            OrderedDict([
                ('organisation', m.organization.name),
                ('organisation_slug', m.organization.slug),
                ('role', m.get_role_display()),
                ('member_since', m.created_at),
                ('teams', [t.name for t in teams if t.organization_id == m.organization_id]),
            ])
            for m in memberships
        ]),
        ('teams_in_other_organisations', [
            {'organisation': t.organization.name, 'team': t.name}
            for t in teams if t.organization_id not in member_org_pks
        ]),
    ])


# ── records that name the person ───────────────────────────────────────────

def _record_models():
    """``[(model, [fields that point at the user]), ...]`` for the record relations."""
    grouped = OrderedDict()
    for _, model, field, handling in handled():
        if handling.export == EXPORT_RECORD:
            grouped.setdefault(model, []).append(field)
    # In the order the model declares them, so "you_are" reads owner before creator.
    return [
        (model, sorted(fields, key=lambda f: f.creation_counter))
        for model, fields in grouped.items()
    ]


def _named_q(fields, user):
    query = Q()
    for field in fields:
        query |= Q(**{field.name: user})
    return query


def _record(obj, user_fields, user, organization, path):
    opts = obj._meta
    fields = OrderedDict()
    for field in opts.concrete_fields:
        if field.primary_key:
            continue
        if field.is_relation:
            if field.related_model is type(user):
                # Links to accounts are never written out: the person's own are
                # named in "you_are", anybody else's are not theirs to receive.
                continue
            related = getattr(obj, field.name)
            fields[field.name] = str(related) if related is not None else None
            continue
        fields[field.name] = _plain(getattr(obj, field.attname))
    return OrderedDict([
        ('id', obj.pk),
        ('type', str(opts.verbose_name)),
        ('you_are', [f.name for f in user_fields if getattr(obj, f.attname) == user.pk]),
        ('organisation', organization.name if organization else None),
        ('team', _team_name(obj, path)),
        ('fields', fields),
    ])


def _plain(value):
    return (value.name or None) if isinstance(value, FieldFile) else value


def _team_name(obj, path):
    """The team a record sits in, found on the way from the record to its organisation."""
    current = obj
    for step in filter(None, path.split('__')):
        current = getattr(current, step, None)
        if current is None:
            return None
        if isinstance(current, Team):
            return current.name
    return None


# ── activity/ ──────────────────────────────────────────────────────────────

def _audit_events(user):
    """Audit events the person caused, and events recorded about their account.

    ``details`` is left out: it is free-form and may name other people. The
    label of the thing acted on is left out when that thing is somebody
    else's account.
    """
    own_pk = str(user.pk)
    events = (
        AuditEvent.objects
        .filter(Q(actor=user) | Q(target_type=USER_TARGET, target_id=own_pk))
        .select_related('organization').order_by('created_at', 'pk')
    )
    rows = []
    for event in events:
        by_you = event.actor_id == user.pk
        about_other_account = event.target_type == USER_TARGET and event.target_id != own_pk
        row = OrderedDict([
            ('when', event.created_at),
            ('action', event.action),
            ('done_by_you', by_you),
            ('organisation', event.organization.name if event.organization else None),
            ('target_type', event.target_type or None),
            ('target', None if about_other_account else (event.target_label or None)),
        ])
        if by_you:
            row['ip_address'] = event.ip_address
            row['user_agent'] = event.user_agent or None
        rows.append(row)
    return rows


def _admin_log(user):
    """What the person changed through the admin site, for those who have used it."""
    rows = []
    entries = LogEntry.objects.filter(user=user).select_related('content_type').order_by(
        'action_time', 'pk')
    for entry in entries:
        content_type = entry.content_type
        kind = f'{content_type.app_label}.{content_type.model}' if content_type else None
        rows.append(OrderedDict([
            ('when', entry.action_time),
            ('action', {1: 'added', 2: 'changed', 3: 'deleted'}.get(entry.action_flag)),
            ('record_type', kind),
            ('record', None if kind == USER_TARGET else entry.object_repr),
        ]))
    return rows


# ── media/ ─────────────────────────────────────────────────────────────────

def _media_files(user):
    profile = UserProfile.objects.filter(user=user).first()
    if profile is None or not profile.avatar:
        return
    name = profile.avatar.name
    if default_storage.exists(name):
        with default_storage.open(name, 'rb') as fh:
            yield name, fh.read()


# ── README.txt ─────────────────────────────────────────────────────────────

def _readme(user, manifest):
    orgs = '\n'.join(
        f'  {org["name"]}' for org in manifest['organizations']
    ) or '  (none)'
    counts = '\n'.join(
        f'  {name:<58} {count:>6}' for name, count in manifest['record_counts'].items()
    ) or '  (none)'
    former = ''
    if manifest['former_organizations']:
        lines = []
        for org_name, per_model in manifest['former_organizations'].items():
            total = sum(per_model.values())
            lines.append(f'  {org_name}: {total} record(s)')
        former = (
            '\nOrganisations you no longer belong to\n'
            '-------------------------------------\n'
            'Records in these organisations still name you. Their content is the\n'
            'organisation\'s, so only the numbers are given here (by record type in\n'
            'former-organisations.json). Ask the organisation for a copy.\n\n'
            + '\n'.join(lines) + '\n'
        )
    files = '\n'.join(f'  media/{name}' for name in manifest['files']) or '  (none)'
    return f"""Your personal data
==================

Account      : {user.get_username()}
Exported at  : {manifest['exported_at']}
Format       : {manifest['format_version']}

Your organisations
------------------
{orgs}

What this archive contains
--------------------------
  account.json           your account (username, name, email, sign-in dates),
                         your profile, whether two-factor sign-in is on, and
                         your notification preferences
  memberships.json       the organisations you belong to, your role in each
                         and your teams
  organisations/<organisation>/<record type>.json
                         every record that names you, in each organisation you
                         belong to. "you_are" says how: owner, created_by,
                         author, participant and so on. Each record carries its
                         own text and dates and the names of the things it
                         belongs to (team, meeting and the like)
  activity/audit-log.json
                         sign-ins and other recorded actions under your
                         account, with the IP address and browser recorded at
                         the time, and events recorded about your account
  activity/admin-site-log.json
                         changes you made through the admin site, if any
  media/                 your avatar, if you uploaded one
  manifest.json          the same summary for programs

What is left out
----------------
Your password, two-factor secrets and backup codes, and your sign-in sessions
are never exported. Other people's names are left out of the records: where a
record links to another person's account, that link is not shown.

Record counts
-------------
{counts}
{former}
Files
-----
{files}
"""
