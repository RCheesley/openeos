import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import groupby

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse
from django.utils.text import slugify
from django.contrib import messages

from .models import (
    Scorecard, ScorecardMetric, ScorecardEntry, _current_week_start,
    build_periods, period_column_label, period_label, period_start_for, shift_period,
)
from .forms import ScorecardForm, ScorecardMetricForm
from apps.accounts.scoping import (
    OrgScopedMixin, get_active_org, get_active_team, get_org_object_or_404,
)
from apps.accounts.team_scope import (
    SCOPE_ALL, count_other_teams, get_scope, get_visible_teams, summarise_other_teams,
)
from apps.accounts.terminology import get_terms
from apps.audit.services import record

SCOPE_SESSION_KEY = 'scorecards_scope'


def _build_periods(n=13, frequency='weekly'):
    """Return list of n period-start dates ending with the current period, oldest first."""
    return build_periods(frequency, n)


def _entries_by_period(metrics, frequency, periods):
    """Map (metric id, period start) to the entry shown for that period.

    An entry belongs to the period its date falls in. Weekly entries are stored
    on their Monday, so each is its own week. Entries for a longer cadence are
    stored on the period's first day, but values entered before cadences were
    honoured sit on a Monday inside the month: those are shown in that month
    (the latest one wins) and are left stored as they are.
    """
    entries = (
        ScorecardEntry.objects
        .filter(
            metric__in=metrics,
            period_start__gte=periods[0],
            period_start__lt=shift_period(frequency, periods[-1], 1),
        )
        .select_related('entered_by')
        .order_by('period_start')
    )
    return {(e.metric_id, period_start_for(frequency, e.period_start)): e for e in entries}


def _current_entries(metrics):
    """Map metric id to the entry for that metric's own current period."""
    current = {}
    for frequency in {m.frequency for m in metrics}:
        group = [m for m in metrics if m.frequency == frequency]
        period = period_start_for(frequency, date.today())
        for (metric_id, _), entry in _entries_by_period(group, frequency, [period]).items():
            current[metric_id] = entry
    return current


def _build_scorecard_table(scorecard, frequency=ScorecardMetric.FREQ_WEEKLY):
    """Build the 13 periods and per-metric cell table for the metrics of one cadence.

    Returns (periods, table) where periods is oldest→newest period-start dates and
    table is [{'metric': m, 'cells': [entry|None, ...], 'period_cells': [(period, entry|None), ...]}]
    aligned to those periods.
    """
    metrics = list(
        scorecard.active_metrics.filter(frequency=frequency).select_related('owner', 'owner__profile')
    )
    periods = build_periods(frequency)
    entry_map = _entries_by_period(metrics, frequency, periods) if metrics else {}

    table = []
    for m in metrics:
        cells = [entry_map.get((m.pk, p)) for p in periods]
        table.append({'metric': m, 'cells': cells, 'period_cells': list(zip(periods, cells))})
    return periods, table


def _build_scorecard_sections(scorecard, weekly=None):
    """Build one table per cadence that has active metrics, weekly first.

    Each cadence has its own 13 period columns, so a board that mixes weekly and
    monthly metrics shows one table for each. ``weekly`` takes an already built
    (periods, table) for the weekly cadence. Shared by the detail view and the
    CSV export so both render the same data.
    """
    sections = []
    for frequency, label in ScorecardMetric.FREQ_CHOICES:
        if weekly is not None and frequency == ScorecardMetric.FREQ_WEEKLY:
            periods, table = weekly
        else:
            periods, table = _build_scorecard_table(scorecard, frequency)
        if not table:
            continue
        sections.append({
            'frequency': frequency,
            'label': label,
            'periods': periods,
            'columns': [
                {
                    'period': p,
                    'label': period_column_label(frequency, p),
                    'title': period_label(frequency, p),
                }
                for p in periods
            ],
            'current': periods[-1],
            'table': table,
        })
    return sections


# ---------------------------------------------------------------------------
# Scorecard CRUD
# ---------------------------------------------------------------------------

class ScorecardListView(LoginRequiredMixin, ListView):
    """The active team's Scorecards, or every visible team's with ``?scope=all``.

    The scope works as on the Rocks list (see ``apps.accounts.team_scope``) and
    is kept in the session under its own key, so the two lists are switched
    independently. The default is the active team, as before.
    """
    model = Scorecard
    template_name = 'scorecards/scorecard_list.html'
    context_object_name = 'scorecards'

    def get_queryset(self):
        if get_scope(self.request, SCOPE_SESSION_KEY) == SCOPE_ALL:
            team_filter = {'team__in': get_visible_teams(self.request)}
        else:
            team = get_active_team(self.request)
            if not team:
                return Scorecard.objects.none()
            team_filter = {'team': team}
        return (
            Scorecard.objects
            .filter(is_active=True, **team_filter)
            .select_related('team')
            .prefetch_related('metrics')
            .order_by('team__name', 'name')
        )

    def _scope_context(self):
        """Which teams the list covers, and how many Scorecards the others have."""
        scope = get_scope(self.request, SCOPE_SESSION_KEY)
        active_team = get_active_team(self.request)
        visible_teams = list(get_visible_teams(self.request))
        other_team_counts = []
        if scope == SCOPE_ALL:
            scoped_teams = visible_teams
        else:
            scoped_teams = [active_team] if active_team else []
            if active_team:
                other_team_counts = count_other_teams(
                    Scorecard.objects.filter(is_active=True), active_team, visible_teams
                )
        return {
            'scope': scope,
            'active_team': active_team,
            'visible_teams': visible_teams,
            'scoped_teams': scoped_teams,
            'other_team_counts': other_team_counts,
            'other_scorecards_total': sum(n for _, n in other_team_counts),
            'other_teams_summary': summarise_other_teams(other_team_counts),
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current_week = _current_week_start()

        # For each scorecard, attach a quick summary for the current week
        summaries = []
        for sc in ctx['scorecards']:
            metrics = list(sc.active_metrics)
            # Each metric is judged on its own current period (week, month, ...).
            entries = _current_entries(metrics)
            on_track = sum(1 for m in metrics if entries.get(m.pk) and entries[m.pk].on_track)
            off_track = sum(1 for m in metrics if entries.get(m.pk) and not entries[m.pk].on_track)
            missing = sum(1 for m in metrics if m.pk not in entries)
            summaries.append({
                'scorecard': sc,
                'metrics': metrics,
                'entries': entries,
                'on_track': on_track,
                'off_track': off_track,
                'missing': missing,
                'total': len(metrics),
            })
        ctx['summaries'] = summaries
        # One group per team, in team-name order, for the all-teams view's headings.
        ctx['teams_summaries'] = [
            (team, list(team_summaries))
            for team, team_summaries in groupby(summaries, key=lambda s: s['scorecard'].team)
        ]
        ctx['current_week'] = current_week
        ctx.update(self._scope_context())
        return ctx


class ScorecardCreateView(LoginRequiredMixin, CreateView):
    model = Scorecard
    form_class = ScorecardForm
    template_name = 'scorecards/scorecard_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = get_active_org(self.request)
        return kw

    def form_valid(self, form):
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.scorecard} "{form.instance.name}" created.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Create'
        return ctx


class ScorecardUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = Scorecard
    form_class = ScorecardForm
    template_name = 'scorecards/scorecard_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.object.team.organization
        return kw

    def form_valid(self, form):
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.scorecard} "{form.instance.name}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class ScorecardDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = Scorecard
    template_name = 'scorecards/scorecard_confirm_delete.html'
    success_url = reverse_lazy('scorecards:list')

    def form_valid(self, form):
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.scorecard} "{self.object.name}" deleted.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Scorecard detail — 13-week table
# ---------------------------------------------------------------------------

class ScorecardDetailView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = Scorecard
    template_name = 'scorecards/scorecard_detail.html'
    context_object_name = 'scorecard'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sc = self.object
        periods, table = _build_scorecard_table(sc)

        ctx['periods'] = periods
        ctx['table'] = table
        ctx['current_week'] = _current_week_start()
        # One table per cadence. A board with only weekly metrics has the one
        # weekly table, with no cadence heading.
        sections = _build_scorecard_sections(sc, weekly=(periods, table))
        ctx['sections'] = sections
        ctx['weekly_only'] = all(s['frequency'] == ScorecardMetric.FREQ_WEEKLY for s in sections)
        ctx['metric_form'] = ScorecardMetricForm(organization=sc.team.organization)
        return ctx


class ScorecardCsvExportView(LoginRequiredMixin, View):
    """Export a scorecard's 13-period history as CSV.

    A board with one cadence is one table. A board that mixes cadences has one
    table per cadence, each with its own heading row, separated by a blank row.
    """

    def get(self, request, pk):
        scorecard = get_org_object_or_404(request, Scorecard, pk=pk)
        sections = _build_scorecard_sections(scorecard)
        if not sections:
            sections = [{'periods': build_periods(ScorecardMetric.FREQ_WEEKLY), 'table': []}]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="{slugify(scorecard.name)}-scorecard.csv"'
        )

        writer = csv.writer(response)
        for index, section in enumerate(sections):
            if index:
                writer.writerow([])
            writer.writerow(
                ['Metric', 'Owner', 'Goal'] + [p.isoformat() for p in section['periods']]
            )
            for row in section['table']:
                metric = row['metric']
                owner_name = metric.owner.get_full_name() or metric.owner.username
                cells = [
                    metric.format_value(entry.value) if entry else ''
                    for entry in row['cells']
                ]
                writer.writerow([metric.name, owner_name, metric.format_goal()] + cells)
        return response


# ---------------------------------------------------------------------------
# Metric CRUD
# ---------------------------------------------------------------------------

class MetricCreateView(LoginRequiredMixin, CreateView):
    model = ScorecardMetric
    form_class = ScorecardMetricForm
    template_name = 'scorecards/metric_form.html'

    def get_scorecard(self):
        return get_org_object_or_404(self.request, Scorecard, pk=self.kwargs['scorecard_pk'])

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.get_scorecard().team.organization
        return kw

    def form_valid(self, form):
        form.instance.scorecard = self.get_scorecard()
        messages.success(self.request, f'Metric "{form.instance.name}" added.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('scorecards:detail', kwargs={'pk': self.kwargs['scorecard_pk']})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['scorecard'] = self.get_scorecard()
        ctx['action'] = 'Add'
        return ctx


class MetricUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = ScorecardMetric
    org_lookup = 'scorecard__team__organization'
    form_class = ScorecardMetricForm
    template_name = 'scorecards/metric_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.object.scorecard.team.organization
        return kw

    def form_valid(self, form):
        messages.success(self.request, f'Metric "{form.instance.name}" updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('scorecards:detail', kwargs={'pk': self.object.scorecard_id})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['scorecard'] = self.object.scorecard
        ctx['action'] = 'Edit'
        return ctx


class MetricDeleteView(LoginRequiredMixin, View):
    """Soft-delete a metric (sets is_active=False)."""

    def post(self, request, pk):
        metric = get_org_object_or_404(
            request, ScorecardMetric, org_lookup='scorecard__team__organization', pk=pk
        )
        scorecard_pk = metric.scorecard_id
        metric.is_active = False
        metric.save(update_fields=['is_active'])
        messages.success(request, f'Metric "{metric.name}" removed.')
        return redirect('scorecards:detail', pk=scorecard_pk)


# ---------------------------------------------------------------------------
# Value entry: POST multiple values in one form
# ---------------------------------------------------------------------------

class ScorecardEntryView(LoginRequiredMixin, View):
    """GET: show the entry form. POST: save/update entries.

    With no query string the form covers every active metric, each for its own
    current period. ``?frequency=monthly&period=2026-09-01`` instead covers the
    metrics of that cadence for one earlier period shown on the board, to fill
    in or correct it; adding ``&metric=<pk>`` narrows it to that one metric.
    """

    template_name = 'scorecards/entry_form.html'

    def _get_rows(self, request, scorecard):
        """Return ([{'metric', 'period', 'entry'}], is_backfill) for this request."""
        metrics = list(scorecard.active_metrics.select_related('owner'))
        frequency = request.GET.get('frequency')
        raw_period = request.GET.get('period')
        fixed_period = None
        if frequency or raw_period:
            if frequency not in dict(ScorecardMetric.FREQ_CHOICES):
                raise Http404
            try:
                fixed_period = date.fromisoformat(raw_period or '')
            except ValueError:
                raise Http404
            # Only the periods the board shows can be filled in or corrected.
            if fixed_period not in build_periods(frequency):
                raise Http404
            metrics = [m for m in metrics if m.frequency == frequency]
            metric_pk = request.GET.get('metric')
            if metric_pk:
                metrics = [m for m in metrics if str(m.pk) == metric_pk]
            if not metrics:
                raise Http404

        existing = {}
        for freq in {m.frequency for m in metrics}:
            group = [m for m in metrics if m.frequency == freq]
            period = fixed_period or period_start_for(freq, date.today())
            for (metric_id, _), entry in _entries_by_period(group, freq, [period]).items():
                existing[metric_id] = entry
        rows = [
            {
                'metric': m,
                'period': fixed_period or period_start_for(m.frequency, date.today()),
                'entry': existing.get(m.pk),
            }
            for m in metrics
        ]
        return rows, fixed_period is not None

    def get(self, request, pk):
        scorecard = get_org_object_or_404(request, Scorecard, pk=pk)
        rows, is_backfill = self._get_rows(request, scorecard)
        return self._render(request, scorecard, rows, is_backfill, errors={})

    def post(self, request, pk):
        scorecard = get_org_object_or_404(request, Scorecard, pk=pk)
        rows, is_backfill = self._get_rows(request, scorecard)
        errors = {}
        saved = 0

        for row in rows:
            metric, entry = row['metric'], row['entry']
            raw = request.POST.get(f'value_{metric.pk}', '').strip()
            notes = request.POST.get(f'notes_{metric.pk}', '').strip()
            if not raw:
                continue  # skip blanks — don't delete existing
            try:
                value = Decimal(raw)
            except InvalidOperation:
                errors[metric.pk] = 'Invalid number.'
                continue

            if entry:
                if entry.value == value and entry.notes == notes:
                    continue  # unchanged: keep who entered it and when
                previous = {'value': str(entry.value), 'notes': entry.notes}
                entry.value = value
                entry.notes = notes
                entry.entered_by = request.user
                entry.save()
                # The entry holds the latest value; the audit log keeps the one it replaced.
                record(
                    'scorecard.entry_changed', request=request,
                    organization=scorecard.team.organization, target=entry,
                    details={
                        'metric': metric.name,
                        'period': metric.period_label(row['period']),
                        'previous_value': previous['value'],
                        'previous_notes': previous['notes'],
                        'new_value': str(value),
                        'new_notes': notes,
                    },
                )
            else:
                row['entry'] = ScorecardEntry.objects.create(
                    metric=metric,
                    period_start=row['period'],
                    value=value,
                    notes=notes,
                    entered_by=request.user,
                )
            saved += 1

        if errors:
            return self._render(request, scorecard, rows, is_backfill, errors=errors)

        messages.success(
            request,
            f'{saved} metric{"s" if saved != 1 else ""} updated for {self._period_phrase(rows)}.',
        )
        return redirect('scorecards:detail', pk=pk)

    @staticmethod
    def _shared_period(rows):
        """Return (frequency, period) when every row is for the same period, else None."""
        found = {(r['metric'].frequency, r['period']) for r in rows}
        return found.pop() if len(found) == 1 else None

    def _period_phrase(self, rows):
        shared = self._shared_period(rows)
        if not shared:
            return 'the current period'
        frequency, period = shared
        if frequency == ScorecardMetric.FREQ_WEEKLY:
            return f'week of {period}'
        return period_label(frequency, period)

    def _render(self, request, scorecard, rows, is_backfill, errors):
        from django.shortcuts import render
        shared = self._shared_period(rows)
        display_rows = []
        for r in rows:
            m, entry = r['metric'], r['entry']
            display_rows.append({
                'metric': m,
                'entry': entry,
                'error': errors.get(m.pk),
                'value_str': str(entry.value) if entry else '',
                'period_label': m.period_label(r['period']),
            })
        current_week = _current_week_start()
        return render(request, self.template_name, {
            'scorecard': scorecard,
            'rows': display_rows,
            'current_week': current_week,
            'period_label': (
                period_label(*shared) if shared
                else f'Week of {current_week.strftime("%b %d, %Y")}' if not rows
                else 'Current period'
            ),
            # Rows for different periods (a board that mixes cadences) each name their own.
            'show_row_periods': bool(rows) and not shared,
            'is_backfill': is_backfill,
        })


# ---------------------------------------------------------------------------
# Escalate off-track metric to Issue
# ---------------------------------------------------------------------------

class MetricEscalateView(LoginRequiredMixin, View):
    """POST-only: create an Issue from an off-track metric entry."""

    @staticmethod
    def _period_phrase(metric, entry):
        if metric.frequency == ScorecardMetric.FREQ_WEEKLY:
            return f'the week of {entry.period_start}'
        return metric.period_label(period_start_for(metric.frequency, entry.period_start))

    def post(self, request, pk):
        entry = get_org_object_or_404(
            request, ScorecardEntry,
            org_lookup='metric__scorecard__team__organization', pk=pk,
        )
        metric = entry.metric

        from apps.issues.models import Issue, IssueActivity
        issue = Issue.objects.create(
            title=f'Off-track: {metric.name}',
            description=(
                f'Metric "{metric.name}" on {metric.scorecard.name} was off-track '
                f'for {self._period_phrase(metric, entry)}.\n\n'
                f'Value: {metric.format_value(entry.value)} '
                f'(goal: {metric.format_goal()})\n'
                f'{("Notes: " + entry.notes) if entry.notes else ""}'
            ),
            originating_team=metric.scorecard.team,
            created_by=request.user,
            issue_type=Issue.TYPE_SHORT_TERM,
            status=Issue.STATUS_OPEN,
        )
        IssueActivity.objects.create(
            issue=issue,
            actor=request.user,
            action=IssueActivity.ACTION_CREATED,
            notes=f'Created from off-track Scorecard metric "{metric.name}".',
        )
        terms = get_terms(request)
        messages.success(request, f'{terms.issue} created for off-track metric "{metric.name}".')
        return redirect('issues:detail', pk=issue.pk)
