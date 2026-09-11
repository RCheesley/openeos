from django.contrib import admin
from .models import Rock, RockDependency, RockMilestone


class RockDependencyInline(admin.TabularInline):
    model = RockDependency
    fk_name = 'rock'
    extra = 0
    raw_id_fields = ['depends_on_rock']


class RockMilestoneInline(admin.TabularInline):
    model = RockMilestone
    extra = 0
    readonly_fields = ['completed_at', 'created_at']
    fields = ['title', 'due_date', 'order', 'is_complete', 'completed_at']


@admin.register(Rock)
class RockAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'team', 'quarter_label', 'status', 'due_date']
    list_filter = ['status', 'quarter', 'year', 'team']
    search_fields = ['title', 'owner__username', 'owner__first_name', 'team__name']
    raw_id_fields = ['owner', 'created_by', 'parent_rock']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [RockMilestoneInline, RockDependencyInline]

    def quarter_label(self, obj):
        return obj.quarter_label
    quarter_label.short_description = 'Quarter'


@admin.register(RockDependency)
class RockDependencyAdmin(admin.ModelAdmin):
    list_display = ['rock', 'depends_on_rock', 'created_at']
    raw_id_fields = ['rock', 'depends_on_rock']
    readonly_fields = ['created_at']


@admin.register(RockMilestone)
class RockMilestoneAdmin(admin.ModelAdmin):
    list_display = ['title', 'rock', 'due_date', 'is_complete', 'order']
    list_filter = ['is_complete', 'rock__team']
    search_fields = ['title', 'rock__title']
    raw_id_fields = ['rock']
    readonly_fields = ['completed_at', 'created_at']
