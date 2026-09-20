"""Plain-text transactional and digest emails for the EOS App.

Each ``send_*`` function checks the recipient's NotificationPreference
before sending (except the invite email, which is transactional and not
subject to opt-out). All are silent no-ops when the recipient has no
email address on file.
"""
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import NotificationPreference


def _send(user, subject, template_name, context):
    if not user.email:
        return False
    send_mail(
        subject=subject,
        message=render_to_string(template_name, {**context, 'user': user, 'site_url': settings.SITE_URL}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )
    return True


def send_overdue_todo_digest(user, todos):
    pref = NotificationPreference.for_user(user)
    if not pref.overdue_todo_digest:
        return False
    count = len(todos)
    subject = f'{count} overdue To-Do{"s" if count != 1 else ""} — EOS App'
    return _send(user, subject, 'notifications/email/overdue_digest.txt', {'todos': todos})


def send_meeting_reminder(user, meeting):
    pref = NotificationPreference.for_user(user)
    if not pref.meeting_reminders:
        return False
    subject = f'Level 10 Meeting today — {meeting.team.name}'
    return _send(user, subject, 'notifications/email/meeting_reminder.txt', {'meeting': meeting})


def send_rock_off_track_alert(rock):
    pref = NotificationPreference.for_user(rock.owner)
    if not pref.rock_off_track_alerts:
        return False
    subject = f'Rock marked off track: {rock.title}'
    return _send(rock.owner, subject, 'notifications/email/rock_off_track.txt', {'rock': rock})


def send_user_invite_email(user, organization, reset_url):
    """Transactional — always sent, not gated by NotificationPreference."""
    subject = f"You've been invited to {organization.name} on EOS App"
    return _send(user, subject, 'notifications/email/user_invite.txt', {
        'organization': organization,
        'reset_url': reset_url,
    })
