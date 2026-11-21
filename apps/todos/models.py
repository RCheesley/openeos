import calendar
from datetime import date, timedelta

from django.db import models, transaction
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Team


def _default_due_date():
    return date.today() + timedelta(days=7)


def _add_months(start, months, day):
    """The date ``months`` after ``start`` on day ``day``, or the month's last day if it is shorter."""
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


class ToDo(models.Model):
    STATUS_OPEN = 'open'
    STATUS_COMPLETE = 'complete'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_COMPLETE, 'Complete'),
    ]

    RECURRENCE_NONE = ''
    RECURRENCE_WEEKLY = 'weekly'
    RECURRENCE_BIWEEKLY = 'biweekly'
    RECURRENCE_MONTHLY = 'monthly'
    RECURRENCE_QUARTERLY = 'quarterly'
    RECURRENCE_CHOICES = [
        (RECURRENCE_NONE, 'Does not repeat'),
        (RECURRENCE_WEEKLY, 'Weekly'),
        (RECURRENCE_BIWEEKLY, 'Every two weeks'),
        (RECURRENCE_MONTHLY, 'Monthly'),
        (RECURRENCE_QUARTERLY, 'Quarterly'),
    ]
    _RECURRENCE_DAYS = {RECURRENCE_WEEKLY: 7, RECURRENCE_BIWEEKLY: 14}
    _RECURRENCE_MONTHS = {RECURRENCE_MONTHLY: 1, RECURRENCE_QUARTERLY: 3}

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
    recurrence = models.CharField(
        max_length=20, choices=RECURRENCE_CHOICES, default=RECURRENCE_NONE, blank=True,
    )
    # The day of the month a monthly or quarterly series aims for, kept so that
    # a series due on the 31st returns to the 31st after a shorter month.
    recurrence_day = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    # The occurrence whose completion created this one. At most one occurrence
    # follows another, which is what stops a second completion creating a duplicate.
    previous_occurrence = models.OneToOneField(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='next_occurrence', editable=False,
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

    # ── Recurrence ───────────────────────────────────────────────────────────

    @property
    def is_recurring(self):
        return bool(self.recurrence)

    @property
    def recurrence_label(self):
        """Text for the marker shown beside a repeating To-Do, e.g. "Repeats weekly"."""
        if not self.recurrence:
            return ''
        return f'Repeats {self.get_recurrence_display().lower()}'

    def _month_anchor(self):
        """The day of the month the series aims for.

        The stored day only counts while the due date still sits where the
        series put it; once somebody moves the due date, the new day wins.
        """
        last_day = calendar.monthrange(self.due_date.year, self.due_date.month)[1]
        if self.recurrence_day and self.due_date.day == min(self.recurrence_day, last_day):
            return self.recurrence_day
        return self.due_date.day

    def next_due_date(self):
        """One interval after this due date (never after the completion date)."""
        if self.recurrence in self._RECURRENCE_DAYS:
            return self.due_date + timedelta(days=self._RECURRENCE_DAYS[self.recurrence])
        if self.recurrence in self._RECURRENCE_MONTHS:
            return _add_months(
                self.due_date, self._RECURRENCE_MONTHS[self.recurrence], self._month_anchor()
            )
        return None

    def _create_next_occurrence(self):
        if not self.recurrence:
            return None
        if ToDo.objects.filter(previous_occurrence=self).exists():
            # Completed, reopened and completed again after its successor was
            # itself completed: the series has already moved on.
            return None
        months = self.recurrence in self._RECURRENCE_MONTHS
        return ToDo.objects.create(
            title=self.title,
            description=self.description,
            owner=self.owner,
            team=self.team,
            due_date=self.next_due_date(),
            linked_rock=self.linked_rock,
            linked_issue=self.linked_issue,
            recurrence=self.recurrence,
            recurrence_day=self._month_anchor() if months else None,
            previous_occurrence=self,
        )

    def mark_complete(self):
        """Complete this To-Do. Returns the next occurrence if one was created."""
        with transaction.atomic():
            # Lock the row so two completions at once cannot both create a successor.
            current = ToDo.objects.select_for_update().get(pk=self.pk)
            if current.is_complete:
                self.status = current.status
                self.completed_at = current.completed_at
                return None
            self.status = self.STATUS_COMPLETE
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'completed_at', 'updated_at'])
            return self._create_next_occurrence()

    def mark_open(self):
        """Reopen this To-Do. Returns True if its open next occurrence was removed.

        The next occurrence only exists because this one was completed, so it
        goes when that is undone. One that has itself been completed is kept
        as a record of work done.
        """
        with transaction.atomic():
            removed, _ = ToDo.objects.filter(
                previous_occurrence=self, status=self.STATUS_OPEN
            ).delete()
            self.status = self.STATUS_OPEN
            self.completed_at = None
            self.save(update_fields=['status', 'completed_at', 'updated_at'])
        return bool(removed)
