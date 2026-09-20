from django.contrib import admin
from .models import NotificationPreference


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'overdue_todo_digest', 'meeting_reminders', 'rock_off_track_alerts']
    list_filter = ['overdue_todo_digest', 'meeting_reminders', 'rock_off_track_alerts']
    search_fields = ['user__username', 'user__email']
    raw_id_fields = ['user']
