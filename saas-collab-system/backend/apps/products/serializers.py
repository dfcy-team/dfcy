from rest_framework import serializers

from .models import ProductResearch, ProductSKU, ProductSPU


class ProductResearchSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = ProductResearch
        fields = (
            "id",
            "tenant_id",
            "research_no",
            "product_name",
            "platform",
            "competitor_url",
            "estimated_sales",
            "estimated_gross_margin",
            "risk_points",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_by_id", "created_at", "updated_at")


class ProductSPUSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductSPU
        fields = (
            "id",
            "tenant_id",
            "spu_code",
            "product_name",
            "category",
            "lifecycle_status",
            "sales_status",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "is_code_frozen", "created_at", "updated_at")

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_code_frozen and "spu_code" in attrs and attrs["spu_code"] != instance.spu_code:
            raise serializers.ValidationError({"spu_code": "Code is frozen and cannot be changed."})
        return attrs


class ProductSKUSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductSKU
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku_code",
            "size",
            "material",
            "selling_points",
            "package_weight",
            "package_volume",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "is_code_frozen", "created_at", "updated_at")

    def validate_spu(self, value):
        request = self.context["request"]
        if value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("SPU does not belong to current tenant.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_code_frozen and "sku_code" in attrs and attrs["sku_code"] != instance.sku_code:
            raise serializers.ValidationError({"sku_code": "Code is frozen and cannot be changed."})
        return attrs
