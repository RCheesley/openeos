from django.contrib import admin
from .models import Meeting, SegueEntry, Headline, MeetingRating


class SegueInline(admin.TabularInline):
    model = SegueEntry
    extra = 0


class HeadlineInline(admin.TabularInline):
    model = Headline
    extra = 0


class RatingInline(admin.TabularInline):
    model = MeetingRating
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ['team', 'scheduled_date', 'status', 'current_segment', 'created_by', 'started_at', 'ended_at']
    list_filter = ['status', 'team__organization']
    search_fields = ['team__name', 'team__organization__name', 'created_by__username']
    readonly_fields = ['started_at', 'ended_at', 'created_at']
    inlines = [SegueInline, HeadlineInline, RatingInline]


@admin.register(Headline)
class HeadlineAdmin(admin.ModelAdmin):
    list_display = ['text', 'headline_type', 'meeting', 'author', 'created_at']
    list_filter = ['headline_type']
    search_fields = ['text']


@admin.register(MeetingRating)
class MeetingRatingAdmin(admin.ModelAdmin):
    list_display = ['meeting', 'participant', 'score']
    list_filter = ['score']
