from django.contrib import admin

from .models import Issue, IssueActivity


class IssueActivityInline(admin.TabularInline):
    model = IssueActivity
    extra = 0
    readonly_fields = ('actor', 'action', 'notes', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'issue_type', 'status', 'originating_team',
        'delegated_to_team', 'created_by', 'created_at',
    )
    list_filter = ('issue_type', 'status', 'originating_team', 'delegated_to_team')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('originating_team', 'delegated_to_team', 'created_by')
    filter_horizontal = ('linked_rocks',)
    inlines = [IssueActivityInline]


@admin.register(IssueActivity)
class IssueActivityAdmin(admin.ModelAdmin):
    list_display = ('issue', 'actor', 'action', 'created_at')
    list_filter = ('action',)
    readonly_fields = ('created_at',)
