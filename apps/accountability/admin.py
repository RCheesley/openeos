from django.contrib import admin
from .models import AccountabilityNode, AccountabilityRole


class RoleInline(admin.TabularInline):
    model = AccountabilityRole
    extra = 1


@admin.register(AccountabilityNode)
class AccountabilityNodeAdmin(admin.ModelAdmin):
    list_display = ['name', 'node_type', 'owner', 'parent', 'organization', 'order']
    list_filter = ['organization', 'node_type']
    inlines = [RoleInline]


@admin.register(AccountabilityRole)
class AccountabilityRoleAdmin(admin.ModelAdmin):
    list_display = ['description', 'node', 'order']
