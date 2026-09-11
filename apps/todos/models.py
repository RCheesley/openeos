from datetime import date, timedelta

from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Team


def _default_due_date():
    return date.today() + timedelta(days=7)


class ToDo(models.Model):
    STATUS_OPEN = 'open'
    STATUS_COMPLETE = 'complete'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_COMPLETE, 'Complete'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='todos'
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name='todos'
    )
    due_date = models.DateField(default=_default_due_date)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    linked_rock = models.ForeignKey(
        'rocks.Rock', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='todos'
    )
    linked_issue = models.ForeignKey(
        'issues.Issue', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='todos'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('todos:update', kwargs={'pk': self.pk})

    # ── State helpers ────────────────────────────────────────────────────────

    @property
    def is_complete(self):
        return self.status == self.STATUS_COMPLETE

    @property
    def is_overdue(self):
        return self.status == self.STATUS_OPEN and self.due_date < date.today()

    @property
    def days_open(self):
        return (date.today() - self.created_at.date()).days

    @property
    def escalation_level(self):
        """0 = ok, 1 = amber warning (8–13 days), 2 = escalate now (14+ days)."""
        if self.is_complete:
            return 0
        d = self.days_open
        if d >= 14:
            return 2
        if d >= 8:
            return 1
        return 0

    def mark_complete(self):
        self.status = self.STATUS_COMPLETE
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])

    def mark_open(self):
        self.status = self.STATUS_OPEN
        self.completed_at = None
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
