from datetime import date, timedelta
from decimal import Decimal

from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import Team


def _current_week_start():
    today = date.today()
    return today - timedelta(days=today.weekday())  # Monday


def _current_month_start():
    return date.today().replace(day=1)


# How often a metric is measured. Weeks start on Monday; months, quarters and
# years follow the calendar (quarters start in January, April, July, October).
FREQ_WEEKLY = 'weekly'
FREQ_MONTHLY = 'monthly'
FREQ_QUARTERLY = 'quarterly'
FREQ_ANNUAL = 'annual'
_MONTHS_PER_PERIOD = {FREQ_MONTHLY: 1, FREQ_QUARTERLY: 3, FREQ_ANNUAL: 12}


def period_start_for(frequency, day):
    """Return the first day of the period of ``frequency`` that contains ``day``."""
    if frequency == FREQ_WEEKLY:
        return day - timedelta(days=day.weekday())  # Monday
    span = _MONTHS_PER_PERIOD[frequency]
    return date(day.year, day.month - (day.month - 1) % span, 1)


def shift_period(frequency, start, count):
    """Return the period start ``count`` periods after ``start`` (before, if negative)."""
    if frequency == FREQ_WEEKLY:
        return start + timedelta(weeks=count)
    months = start.year * 12 + (start.month - 1) + count * _MONTHS_PER_PERIOD[frequency]
    return date(months // 12, months % 12 + 1, 1)


def build_periods(frequency, n=13, today=None):
    """Return the ``n`` period starts ending with the current period, oldest first."""
    latest = period_start_for(frequency, today or date.today())
    return [shift_period(frequency, latest, -i) for i in range(n - 1, -1, -1)]


def period_label(frequency, start):
    """A period's name in a sentence or page heading, such as "November 2026"."""
    if frequency == FREQ_WEEKLY:
        return f'Week of {start.strftime("%b %d, %Y")}'
    if frequency == FREQ_MONTHLY:
        return start.strftime('%B %Y')
    if frequency == FREQ_QUARTERLY:
        return f'Q{(start.month - 1) // 3 + 1} {start.year}'
    return str(start.year)


def period_column_label(frequency, start):
    """A period's short name for a table column heading."""
    if frequency == FREQ_WEEKLY:
        return f'{start.strftime("%b")} {start.day}'
    if frequency == FREQ_MONTHLY:
        return start.strftime('%b %Y')
    return period_label(frequency, start)


class Scorecard(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='scorecards')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['team__name', 'name']

    def __str__(self):
        return f'{self.name} ({self.team.name})'

    def get_absolute_url(self):
        return reverse('scorecards:detail', kwargs={'pk': self.pk})

    @property
    def active_metrics(self):
        return self.metrics.filter(is_active=True).order_by('order', 'name')

    @property
    def metric_count(self):
        return self.metrics.filter(is_active=True).count()

    @property
    def count_ok(self):
        """Recommended range: 5-15 metrics."""
        n = self.metric_count
        return 5 <= n <= 15


class ScorecardMetric(models.Model):
    TYPE_INTEGER = 'integer'
    TYPE_FLOAT = 'float'
    TYPE_PERCENTAGE = 'percentage'
    TYPE_CHOICES = [
        (TYPE_INTEGER, 'Integer'),
        (TYPE_FLOAT, 'Float'),
        (TYPE_PERCENTAGE, 'Percentage'),
    ]

    DIR_ABOVE = 'above'
    DIR_BELOW = 'below'
    DIR_EQUAL = 'equal'
    DIR_CHOICES = [
        (DIR_ABOVE, 'At or above goal (higher is better)'),
        (DIR_BELOW, 'At or below goal (lower is better)'),
        (DIR_EQUAL, 'Equal to goal'),
    ]

    FREQ_WEEKLY = FREQ_WEEKLY
    FREQ_MONTHLY = FREQ_MONTHLY
    FREQ_QUARTERLY = FREQ_QUARTERLY
    FREQ_ANNUAL = FREQ_ANNUAL
    FREQ_CHOICES = [
        (FREQ_WEEKLY, 'Weekly'),
        (FREQ_MONTHLY, 'Monthly'),
        (FREQ_QUARTERLY, 'Quarterly'),
        (FREQ_ANNUAL, 'Annual'),
    ]

    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name='metrics')
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='scorecard_metrics')
    metric_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_INTEGER)
    goal_value = models.DecimalField(max_digits=12, decimal_places=4)
    goal_direction = models.CharField(max_length=10, choices=DIR_CHOICES, default=DIR_ABOVE)
    frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default=FREQ_WEEKLY)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.name} ({self.scorecard.name})'

    def format_value(self, value):
        if value is None:
            return '—'
        # Thousands separators: 10000.00 reads as a hundred thousand at a glance.
        if self.metric_type == self.TYPE_INTEGER:
            return f'{int(value):,}'
        if self.metric_type == self.TYPE_PERCENTAGE:
            return f'{value:.1f}%'
        return f'{value:,.2f}'

    def format_goal(self):
        label = {self.DIR_ABOVE: '≥', self.DIR_BELOW: '≤', self.DIR_EQUAL: '='}[self.goal_direction]
        return f'{label} {self.format_value(self.goal_value)}'

    def compute_on_track(self, value):
        v, g = Decimal(str(value)), self.goal_value
        if self.goal_direction == self.DIR_ABOVE:
            return v >= g
        if self.goal_direction == self.DIR_BELOW:
            return v <= g
        return v == g

    def current_period_start(self):
        return period_start_for(self.frequency, date.today())

    def period_label(self, start):
        return period_label(self.frequency, start)

    def latest_entry(self):
        return self.entries.order_by('-period_start').first()


class ScorecardEntry(models.Model):
    metric = models.ForeignKey(ScorecardMetric, on_delete=models.CASCADE, related_name='entries')
    period_start = models.DateField()
    value = models.DecimalField(max_digits=12, decimal_places=4)
    on_track = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='scorecard_entries'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # When the value was last saved. Empty on entries made before this was recorded.
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-period_start']
        unique_together = [['metric', 'period_start']]

    def __str__(self):
        return f'{self.metric.name} @ {self.period_start}: {self.value}'

    def save(self, *args, **kwargs):
        self.on_track = self.metric.compute_on_track(self.value)
        super().save(*args, **kwargs)

    @property
    def entered_at(self):
        """When the value shown was saved: the last change, or else the first entry."""
        return self.updated_at or self.created_at

    @property
    def cell_class(self):
        return 'table-success' if self.on_track else 'table-danger'
