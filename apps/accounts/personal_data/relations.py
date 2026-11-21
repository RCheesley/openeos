"""Every place a record points at a user account, and what is done about it.

``USER_RELATIONS`` is written by hand on purpose. The export and the erasure
both walk the model registry (:func:`discover`) and look each relation up
here, so a model that gains a new link to the user makes both refuse to run,
and fails the registry test, until somebody decides what it means for a
person's copy of their data and for their erasure.
"""
from dataclasses import dataclass

from django.apps import apps
from django.contrib.auth import get_user_model

# What the personal export does with a relation.
EXPORT_ACCOUNT = 'account'      # written into account.json or memberships.json
EXPORT_RECORD = 'record'        # a record the person is named on, listed per organisation
EXPORT_ACTIVITY = 'activity'    # the instance's own logs of what the person did
EXPORT_NEVER = 'never'          # holds secrets, or nothing about the person

# What erasure does with a relation.
ERASE_REASSIGN = 'reassign'     # point the row at the shared "Former member" account
ERASE_KEEP = 'keep'             # leave the row on the person's own, anonymised account
ERASE_DELETE = 'delete'         # remove the row


@dataclass(frozen=True)
class Handling:
    export: str
    erase: str
    reason: str


def _h(export, erase, reason):
    return Handling(export, erase, reason)


# Keyed ``app_label.model_name.field_name``.
USER_RELATIONS = {
    # ── the account itself ────────────────────────────────────────────────
    'accounts.membership.user': _h(
        EXPORT_ACCOUNT, ERASE_DELETE,
        'Belonging to an organisation ends with the account.'),
    'accounts.userprofile.user': _h(
        EXPORT_ACCOUNT, ERASE_KEEP,
        'The row stays because pages expect every account to have one; the avatar '
        'and the team memberships on it are removed.'),
    'notifications.notificationpreference.user': _h(
        EXPORT_ACCOUNT, ERASE_KEEP,
        'The row stays for the same reason; every preference is switched off.'),
    'auth.user_groups.user': _h(
        EXPORT_ACCOUNT, ERASE_DELETE, 'Site-wide groups are removed with every other right.'),
    'auth.user_user_permissions.user': _h(
        EXPORT_NEVER, ERASE_DELETE,
        'Site-wide permissions say what the instance lets the account do, not '
        'anything about the person; they are removed on erasure.'),
    'otp_totp.totpdevice.user': _h(
        EXPORT_NEVER, ERASE_DELETE,
        'Holds the authenticator secret. The export says only whether two-factor '
        'sign-in is on.'),
    'otp_static.staticdevice.user': _h(
        EXPORT_NEVER, ERASE_DELETE,
        'Holds the backup codes. The export says only how many are left.'),

    # ── records that must keep an owner (PROTECT) ─────────────────────────
    'rocks.rock.owner': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The record is the organisation\'s and needs an owner.'),
    'todos.todo.owner': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The record is the organisation\'s and needs an owner.'),
    'scorecards.scorecardmetric.owner': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The record is the organisation\'s and needs an owner.'),

    # ── who created, wrote or last edited something ───────────────────────
    'rocks.rock.created_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'History keeps a creator, without the name.'),
    'rocks.rockcheckin.created_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The check-in text is the organisation\'s record.'),
    'issues.issue.created_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'History keeps a creator, without the name.'),
    'issues.issueactivity.actor': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'Comments and activity are the organisation\'s record.'),
    'scorecards.scorecardentry.entered_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The figure and its note are the organisation\'s record.'),
    'vto.vtosection.last_edited_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The section text is the organisation\'s record.'),
    'vto.vtosectionhistory.edited_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'Past versions are the organisation\'s record.'),
    'accountability.accountabilitynode.owner': _h(
        EXPORT_RECORD, ERASE_REASSIGN,
        'The seat shows that somebody who has left held it, until it is filled again.'),
    'meetings.meeting.created_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'History keeps a creator, without the name.'),
    'meetings.meetingnote.updated_by': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'Meeting notes are the organisation\'s record.'),
    'meetings.headline.author': _h(
        EXPORT_RECORD, ERASE_REASSIGN, 'The headline text is the organisation\'s record.'),

    # ── one row per person per meeting ────────────────────────────────────
    'meetings.segueentry.participant': _h(
        EXPORT_RECORD, ERASE_KEEP,
        'One row per person per meeting, so two former members of the same meeting '
        'cannot share one account. The row stays on the anonymised account.'),
    'meetings.meetingrating.participant': _h(
        EXPORT_RECORD, ERASE_KEEP,
        'One row per person per meeting, and deleting it would change the '
        'meeting\'s average. The row stays on the anonymised account.'),

    # ── the instance's logs ───────────────────────────────────────────────
    'audit.auditevent.actor': _h(
        EXPORT_ACTIVITY, ERASE_REASSIGN,
        'The event stays; the username, IP address and browser on it are removed.'),
    'admin.logentry.user': _h(
        EXPORT_ACTIVITY, ERASE_REASSIGN,
        'The admin site\'s history of changes stays, without the name.'),
}


class UnhandledRelation(Exception):
    """A model points at the user account and ``USER_RELATIONS`` does not say what to do."""

    def __init__(self, keys):
        self.keys = sorted(keys)
        super().__init__(
            'These fields point at the user account but are not listed in '
            'apps.accounts.personal_data.relations.USER_RELATIONS: '
            + ', '.join(self.keys)
            + '. Decide what the personal export and the erasure do with each one.'
        )


def key_for(model, field):
    return f'{model._meta.app_label}.{model._meta.model_name}.{field.name}'


def discover():
    """Every concrete field, on any installed model, that points at the user model.

    Returns ``[(key, model, field), ...]`` in a stable order. The automatic
    tables behind many-to-many fields are included, so a many-to-many to the
    user shows up as the foreign key on its through table.
    """
    user_model = get_user_model()
    found = []
    for model in apps.get_models(include_auto_created=True):
        if model._meta.proxy:
            continue
        for field in model._meta.concrete_fields:
            if field.is_relation and field.related_model is user_model:
                found.append((key_for(model, field), model, field))
    return sorted(found, key=lambda item: item[0])


def handled():
    """``[(key, model, field, Handling), ...]``, or :class:`UnhandledRelation`."""
    found = discover()
    missing = [key for key, _, _ in found if key not in USER_RELATIONS]
    if missing:
        raise UnhandledRelation(missing)
    return [(key, model, field, USER_RELATIONS[key]) for key, model, field in found]
