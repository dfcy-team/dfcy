from django.contrib import admin

from .models import (
    PurchaseOrder,
    SupplyProductionProgress,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_no", "tenant", "sku_code", "supplier_id", "quantity", "status", "approval_status")
    search_fields = ("po_no", "sku_code")
    list_filter = ("status", "approval_status")


class SupplyPurchaseOrderLineInline(admin.TabularInline):
    model = SupplyPurchaseOrderLine
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(SupplyPurchaseOrder)
class SupplyPurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_no",
        "tenant",
        "supplier",
        "status",
        "shipping_route",
        "completed_quantity",
        "version",
        "updated_at",
    )
    search_fields = ("order_no", "supplier__code", "supplier__name", "source_record_id")
    list_filter = ("status", "shipping_route", "currency")
    readonly_fields = (
        "status",
        "shipping_route",
        "shipping_route_decided_at",
        "shipping_route_decided_by",
        "completed_quantity",
        "version",
        "accepted_at",
        "production_started_at",
        "production_completed_at",
        "created_at",
        "updated_at",
    )
    inlines = (SupplyPurchaseOrderLineInline,)


@admin.register(SupplyProductionProgress)
class SupplyProductionProgressAdmin(admin.ModelAdmin):
    list_display = ("order", "completed_quantity", "progress_percent", "actor", "created_at")
    search_fields = ("order__order_no", "request_id")
    readonly_fields = (
        "tenant",
        "order",
        "completed_quantity",
        "progress_percent",
        "note",
        "actor",
        "request_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupplyPurchaseOrderEvent)
class SupplyPurchaseOrderEventAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "action",
        "actor_type",
        "before_status",
        "after_status",
        "before_shipping_route",
        "after_shipping_route",
        "created_at",
    )
    search_fields = ("order__order_no", "idempotency_key")
    readonly_fields = (
        "tenant",
        "order",
        "action",
        "idempotency_key",
        "actor",
        "actor_type",
        "before_status",
        "after_status",
        "before_shipping_route",
        "after_shipping_route",
        "payload",
        "request_hash",
        "response_snapshot",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
