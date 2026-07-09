from django.contrib import admin

from .models import PurchaseOrder


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_no", "tenant", "sku_code", "supplier_id", "quantity", "status", "approval_status")
    search_fields = ("po_no", "sku_code")
    list_filter = ("status", "approval_status")
