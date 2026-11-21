from django.contrib import admin

from .models import Connection, OrganizationApiAccess


@admin.register(OrganizationApiAccess)
class OrganizationApiAccessAdmin(admin.ModelAdmin):
    list_display = ('organization', 'enabled', 'updated_by', 'updated_at')
    list_filter = ('enabled',)


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ('application', 'user', 'organization', 'approved_at', 'last_used_at', 'revoked_at')
    list_filter = ('organization',)
    readonly_fields = ('user', 'application', 'organization', 'scope', 'approved_at', 'last_used_at', 'revoked_at')

    def has_add_permission(self, request):
        return False
