from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
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


# How an entry was judged against its metric when it was saved.
STATUS_ON_TRACK = 'on_track'
STATUS_WARNING = 'warning'
STATUS_OFF_TRACK = 'off_track'
STATUS_LABELS = {
    STATUS_ON_TRACK: 'On track',
    STATUS_WARNING: 'Warning',
    STATUS_OFF_TRACK: 'Off track',
}
# Each state has its own icon as well as its own colour, so it never rests on colour alone.
_STATUS_ICONS = {
    STATUS_ON_TRACK: 'bi-check-circle',
    STATUS_WARNING: 'bi-exclamation-circle',
    STATUS_OFF_TRACK: 'bi-x-circle',
}
_STATUS_CELL_CLASSES = {
    STATUS_ON_TRACK: 'table-success',
    STATUS_WARNING: 'table-warning',
    STATUS_OFF_TRACK: 'table-danger',
}
# White on Bootstrap's amber fails contrast, so the warning badge has dark text.
_STATUS_BADGE_CLASSES = {
    STATUS_ON_TRACK: 'bg-success',
    STATUS_WARNING: 'bg-warning text-dark',
    STATUS_OFF_TRACK: 'bg-danger',
}


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
    # Optional. Where the warning band ends: values between this and the goal
    # are neither on track nor off track. See compute_status().
    warning_value = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
        help_text=(
            'Optional. A value that misses the goal but is no worse than this is '
            'shown as a warning instead of off track.'
        ),
    )
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

    def format_warning(self):
        """The warning band in a few words, or '' when the metric has none."""
        if self.warning_value is None:
            return ''
        if self.goal_direction == self.DIR_ABOVE:
            return f'Warning from {self.format_value(self.warning_value)}'
        if self.goal_direction == self.DIR_BELOW:
            return f'Warning up to {self.format_value(self.warning_value)}'
        return f'Warning within {self.format_value(self.warning_tolerance)}'

    @property
    def warning_tolerance(self):
        """For an "equal to" goal: how far either side of the goal still counts as a warning."""
        if self.warning_value is None:
            return None
        return abs(self.goal_value - self.warning_value)

    def clean(self):
        super().clean()
        if self.warning_value is None or self.goal_value is None:
            return
        if self.goal_direction == self.DIR_ABOVE and self.warning_value >= self.goal_value:
            message = 'For a goal of "at or above", the warning value must be below the goal.'
        elif self.goal_direction == self.DIR_BELOW and self.warning_value <= self.goal_value:
            message = 'For a goal of "at or below", the warning value must be above the goal.'
        elif self.warning_value == self.goal_value:
            message = 'The warning value must differ from the goal.'
        else:
            return
        raise ValidationError({'warning_value': message})

    def compute_on_track(self, value):
        v, g = Decimal(str(value)), self.goal_value
        if self.goal_direction == self.DIR_ABOVE:
            return v >= g
        if self.goal_direction == self.DIR_BELOW:
            return v <= g
        return v == g

    def compute_status(self, value):
        """Judge a value as on track, warning or off track.

        Without a warning value there are two states, as before. With one, a
        value that misses the goal but stays inside the band is a warning:

        * at or above 10, warning 8: 10 and over on track, 8 to under 10
          warning, under 8 off track;
        * at or below 10, warning 12: 10 and under on track, over 10 to 12
          warning, over 12 off track;
        * equal to 10, warning 8 (or 12): exactly 10 on track, anything else
          from 8 to 12 warning, the rest off track. An exact goal has no better
          side, so the band reaches the same distance either way.
        """
        if self.compute_on_track(value):
            return STATUS_ON_TRACK
        if self.warning_value is None:
            return STATUS_OFF_TRACK
        v, w = Decimal(str(value)), self.warning_value
        if self.goal_direction == self.DIR_ABOVE:
            in_band = v >= w
        elif self.goal_direction == self.DIR_BELOW:
            in_band = v <= w
        else:
            in_band = abs(v - self.goal_value) <= self.warning_tolerance
        return STATUS_WARNING if in_band else STATUS_OFF_TRACK

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
    # The judgement made when the value was saved. ``on_track`` says whether the
    # goal was met; ``in_warning`` marks a miss that stayed inside the metric's
    # warning band. Both false is off track. Entries saved before warning bands
    # existed have ``in_warning`` false, so they stay on track or off track.
    on_track = models.BooleanField(default=True)
    in_warning = models.BooleanField(default=False)
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
        status = self.metric.compute_status(self.value)
        self.on_track = status == STATUS_ON_TRACK
        self.in_warning = status == STATUS_WARNING
        super().save(*args, **kwargs)

    @property
    def status(self):
        if self.on_track:
            return STATUS_ON_TRACK
        return STATUS_WARNING if self.in_warning else STATUS_OFF_TRACK

    @property
    def status_label(self):
        return STATUS_LABELS[self.status]

    @property
    def status_icon(self):
        return _STATUS_ICONS[self.status]

    @property
    def is_off_track(self):
        return self.status == STATUS_OFF_TRACK

    @property
    def entered_at(self):
        """When the value shown was saved: the last change, or else the first entry."""
        return self.updated_at or self.created_at

    @property
    def cell_class(self):
        return _STATUS_CELL_CLASSES[self.status]

    @property
    def badge_class(self):
        return _STATUS_BADGE_CLASSES[self.status]
