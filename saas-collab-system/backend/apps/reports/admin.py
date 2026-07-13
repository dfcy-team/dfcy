from django.contrib import admin

from .models import MetricAggregate, MetricAggregateLineage, MetricDataPoint, MetricDefinition


@admin.register(MetricDefinition)
class MetricDefinitionAdmin(admin.ModelAdmin):
    list_display = ("metric_code", "version", "tenant", "aggregation_method", "status")
    list_filter = ("status", "aggregation_method")
    search_fields = ("metric_code", "name", "tenant__code")

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MetricDataPoint)
class MetricDataPointAdmin(admin.ModelAdmin):
    list_display = ("metric_definition", "tenant", "source_table", "source_batch", "quality_status", "occurred_at")
    list_filter = ("quality_status", "source_table")
    search_fields = ("source_batch", "source_record_id", "tenant__code")
    readonly_fields = tuple(field.name for field in MetricDataPoint._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MetricAggregate)
class MetricAggregateAdmin(admin.ModelAdmin):
    list_display = ("metric_definition", "tenant", "granularity", "period_start", "period_end", "quality_status")
    list_filter = ("granularity", "quality_status")
    search_fields = ("metric_definition__metric_code", "tenant__code")
    readonly_fields = tuple(field.name for field in MetricAggregate._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MetricAggregateLineage)
class MetricAggregateLineageAdmin(admin.ModelAdmin):
    list_display = ("aggregate", "tenant", "source_table", "source_batch", "calculation_task")
    list_filter = ("source_table",)
    search_fields = ("source_batch", "calculation_task", "tenant__code")
    readonly_fields = tuple(field.name for field in MetricAggregateLineage._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
