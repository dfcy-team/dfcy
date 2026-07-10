from django.contrib import admin

from .models import (
    ProductResearch,
    ProductSKU,
    ProductSPU,
    ProductStatusRecommendation,
    ProductStatusSnapshot,
    ProductStatusTransition,
)


@admin.register(ProductResearch)
class ProductResearchAdmin(admin.ModelAdmin):
    list_display = ("research_no", "tenant", "product_name", "platform", "approval_status", "created_at")
    search_fields = ("research_no", "product_name")
    list_filter = ("approval_status", "platform")


@admin.register(ProductSPU)
class ProductSPUAdmin(admin.ModelAdmin):
    list_display = ("spu_code", "tenant", "product_name", "lifecycle_status", "sales_status", "is_code_frozen")
    search_fields = ("spu_code", "product_name")
    list_filter = ("lifecycle_status", "sales_status", "is_code_frozen")


@admin.register(ProductSKU)
class ProductSKUAdmin(admin.ModelAdmin):
    list_display = ("sku_code", "tenant", "spu", "size", "is_code_frozen")
    search_fields = ("sku_code", "spu__spu_code", "spu__product_name")
    list_filter = ("is_code_frozen",)


@admin.register(ProductStatusSnapshot)
class ProductStatusSnapshotAdmin(admin.ModelAdmin):
    list_display = ("tenant", "spu", "sku", "source", "calculated_status", "calculated_at")
    search_fields = ("source_reference", "spu__spu_code", "sku__sku_code")
    list_filter = ("source", "calculated_status", "tenant")


@admin.register(ProductStatusRecommendation)
class ProductStatusRecommendationAdmin(admin.ModelAdmin):
    list_display = ("tenant", "spu", "sku", "recommended_status", "status", "confidence", "created_at")
    search_fields = ("reason_code", "reason_detail", "spu__spu_code", "sku__sku_code")
    list_filter = ("recommended_status", "status", "tenant")


@admin.register(ProductStatusTransition)
class ProductStatusTransitionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "spu", "sku", "from_status", "to_status", "trigger_type", "approved_by", "created_at")
    search_fields = ("reason", "spu__spu_code", "sku__sku_code", "approved_by__username")
    list_filter = ("from_status", "to_status", "trigger_type", "tenant")
