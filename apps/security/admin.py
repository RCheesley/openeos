from django.contrib import admin

from .models import Throttle


@admin.register(Throttle)
class ThrottleAdmin(admin.ModelAdmin):
    """Counters can be looked at and deleted (which lifts a lock-out), nothing else."""

    list_display = ['scope', 'throttling_failure_count', 'throttling_failure_timestamp']
    list_filter = ['scope']
    readonly_fields = ['scope', 'key', 'throttling_failure_count', 'throttling_failure_timestamp']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
