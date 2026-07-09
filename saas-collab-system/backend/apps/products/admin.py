from django.contrib import admin

from .models import ProductResearch, ProductSKU, ProductSPU


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
