from datetime import date
from itertools import groupby

from django.core.management.base import BaseCommand

from apps.meetings.models import Meeting
from apps.notifications.emails import send_meeting_reminder, send_overdue_todo_digest
from apps.todos.models import ToDo


class Command(BaseCommand):
    help = (
        "Send the daily overdue To-Do digest and today's meeting reminders. "
        "Intended to run once per day via an external scheduler (cron, systemd timer, "
        "a hosting platform's scheduled jobs, etc.) — see DevOps docs."
    )

    def handle(self, *args, **options):
        digest_count = self._send_overdue_digests()
        reminder_count = self._send_meeting_reminders()
        self.stdout.write(self.style.SUCCESS(
            f'Sent {digest_count} overdue To-Do digest(s) and {reminder_count} meeting reminder(s).'
        ))

    def _send_overdue_digests(self):
        overdue = (
            ToDo.objects
            .filter(status=ToDo.STATUS_OPEN, due_date__lt=date.today())
            .select_related('owner', 'team')
            .order_by('owner_id', 'due_date')
        )
        sent = 0
        for owner, todos in groupby(overdue, key=lambda t: t.owner):
            if send_overdue_todo_digest(owner, list(todos)):
                sent += 1
        return sent

    def _send_meeting_reminders(self):
        meetings = (
            Meeting.objects
            .filter(scheduled_date=date.today(), status=Meeting.STATUS_SCHEDULED)
            .select_related('team')
        )
        sent = 0
        for meeting in meetings:
            members = meeting.team.members.select_related('user')
            for profile in members:
                if send_meeting_reminder(profile.user, meeting):
                    sent += 1
        return sent
