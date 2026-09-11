from django.contrib import admin

from .models import Scorecard, ScorecardMetric, ScorecardEntry


class ScorecardMetricInline(admin.TabularInline):
    model = ScorecardMetric
    extra = 1
    fields = ('name', 'owner', 'metric_type', 'goal_value', 'goal_direction', 'frequency', 'order', 'is_active')


@admin.register(Scorecard)
class ScorecardAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'metric_count', 'is_active', 'created_at')
    list_filter = ('is_active', 'team')
    search_fields = ('name', 'team__name')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ScorecardMetricInline]


@admin.register(ScorecardMetric)
class ScorecardMetricAdmin(admin.ModelAdmin):
    list_display = ('name', 'scorecard', 'owner', 'metric_type', 'goal_value', 'goal_direction', 'frequency', 'is_active')
    list_filter = ('metric_type', 'goal_direction', 'frequency', 'is_active')
    search_fields = ('name', 'scorecard__name')


@admin.register(ScorecardEntry)
class ScorecardEntryAdmin(admin.ModelAdmin):
    list_display = ('metric', 'period_start', 'value', 'on_track', 'entered_by', 'created_at')
    list_filter = ('on_track', 'period_start')
    readonly_fields = ('on_track', 'created_at')
    date_hierarchy = 'period_start'
