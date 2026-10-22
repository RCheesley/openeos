"""Plain-text transactional and digest emails.

Each ``send_*`` function checks the recipient's NotificationPreference
before sending (except the invite email, which is transactional and not
subject to opt-out). All return False without sending when the recipient
has no email address on file.
"""
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from apps.accounts.branding import brand_for

from .models import NotificationPreference


def _from_email(organization, brand):
    """The organisation's sender name on the configured sender address."""
    if organization is None:
        return settings.DEFAULT_FROM_EMAIL
    address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    return formataddr((organization.email_from_name or brand.name, address))


def _send(user, subject, template_name, context, organization=None):
    """Links use the organisation's own domain when it has one, else SITE_URL."""
    if not user.email:
        return False
    brand = brand_for(organization)
    site_url = (organization.site_url if organization else '') or settings.SITE_URL
    send_mail(
        subject=subject,
        message=render_to_string(
            template_name, {**context, 'user': user, 'site_url': site_url, 'brand': brand},
        ),
        from_email=_from_email(organization, brand),
        recipient_list=[user.email],
        fail_silently=True,
    )
    return True


def send_overdue_todo_digest(user, todos, organization=None):
    pref = NotificationPreference.for_user(user)
    if not pref.overdue_todo_digest:
        return False
    count = len(todos)
    brand = brand_for(organization)
    subject = f'{count} overdue To-Do{"s" if count != 1 else ""} — {brand.name}'
    return _send(
        user, subject, 'notifications/email/overdue_digest.txt', {'todos': todos},
        organization=organization,
    )


def send_meeting_reminder(user, meeting):
    pref = NotificationPreference.for_user(user)
    if not pref.meeting_reminders:
        return False
    subject = f'Level 10 Meeting today — {meeting.team.name}'
    return _send(
        user, subject, 'notifications/email/meeting_reminder.txt', {'meeting': meeting},
        organization=meeting.team.organization,
    )


def send_rock_off_track_alert(rock):
    pref = NotificationPreference.for_user(rock.owner)
    if not pref.rock_off_track_alerts:
        return False
    subject = f'Rock marked off track: {rock.title}'
    return _send(
        rock.owner, subject, 'notifications/email/rock_off_track.txt', {'rock': rock},
        organization=rock.team.organization,
    )


def send_user_invite_email(user, organization, reset_url):
    """Transactional — always sent, not gated by NotificationPreference."""
    subject = f"You've been invited to {organization.get_display_name()}"
    return _send(user, subject, 'notifications/email/user_invite.txt', {
        'organization': organization,
        'reset_url': reset_url,
    }, organization=organization)
