from django.contrib import admin

from .models import SupplierShipment, SupplierTask


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
