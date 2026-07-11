from django.contrib import admin

from .models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask


@admin.register(SupplierTask)
class SupplierTaskAdmin(admin.ModelAdmin):
    list_display = ("task_no", "tenant", "supplier_id", "sku_code", "status", "is_overdue")
    search_fields = ("task_no", "sku_code")
    list_filter = ("status", "is_overdue")


@admin.register(SupplierShipment)
class SupplierShipmentAdmin(admin.ModelAdmin):
    list_display = ("shipment_no", "tenant", "supplier_id", "sku_code", "ship_quantity", "status")
    search_fields = ("shipment_no", "sku_code", "tracking_no")
    list_filter = ("status",)


@admin.register(SupplierPerformanceSnapshot)
class SupplierPerformanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("tenant", "supplier_id", "period_start", "period_end", "total_score", "calculated_at")
    search_fields = ("supplier_id",)
    list_filter = ("period_start", "period_end")
