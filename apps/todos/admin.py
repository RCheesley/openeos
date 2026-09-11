from django.contrib import admin

from .models import ToDo


@admin.register(ToDo)
class ToDoAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'team', 'due_date', 'status', 'linked_rock', 'linked_issue', 'created_at')
    list_filter = ('status', 'team', 'due_date')
    search_fields = ('title', 'description', 'owner__username', 'owner__first_name')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    raw_id_fields = ('owner',)
    date_hierarchy = 'due_date'
