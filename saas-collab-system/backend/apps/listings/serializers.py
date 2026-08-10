from rest_framework import serializers

from .models import (
    ListingAttributeMapping,
    ListingProfile,
    ListingPublicationJob,
    ListingTask,
    ListingTaskErrorLog,
    ListingTaskStepLog,
    ListingTemplate,
    ListingVariant,
    PlatformCategoryMapping,
)


class ListingTemplateSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    platform_code = serializers.CharField(source="platform.code", read_only=True)

    class Meta:
        model = ListingTemplate
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")

    def validate_platform(self, value):
        if value.tenant_id != self.context["request"].user.tenant_id:
            raise serializers.ValidationError("Platform must belong to the current tenant.")
        return value


class ListingVariantSerializer(serializers.ModelSerializer):
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True)
    legacy_sku_code = serializers.CharField(source="sku.legacy_sku_code", read_only=True)
    color_code = serializers.CharField(source="sku.color_code", read_only=True)
    specification = serializers.CharField(source="sku.specification", read_only=True)
    spec_values = serializers.JSONField(source="sku.spec_values", read_only=True)
    purchase_price = serializers.DecimalField(source="sku.purchase_price", max_digits=14, decimal_places=4, read_only=True, allow_null=True)

    class Meta:
        model = ListingVariant
        fields = "__all__"
        read_only_fields = ("profile",)
        extra_kwargs = {
            "seller_sku": {"required": False},
            "price": {"required": False},
        }


class ListingProfileSerializer(serializers.ModelSerializer):
    variants = ListingVariantSerializer(many=True, required=False)
    spu_code = serializers.CharField(source="product.spu_code", read_only=True)
    legacy_spu_code = serializers.CharField(source="product.legacy_spu_code", read_only=True)
    product_name = serializers.CharField(source="product.product_name", read_only=True)
    brand = serializers.CharField(source="product.brand", read_only=True)
    platform = serializers.CharField(source="store.platform.code", read_only=True)
    country_code = serializers.CharField(source="store.country_code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = ListingProfile
        fields = "__all__"
        read_only_fields = (
            "tenant", "created_by", "status", "validation_errors", "external_listing_id",
            "approved_by", "approved_at", "created_at", "updated_at",
        )

    def validate(self, attrs):
        tenant_id = self.context["request"].user.tenant_id
        for field in ("product", "store", "template"):
            value = attrs.get(field)
            if value is not None and value.tenant_id != tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        return attrs

    def create(self, validated_data):
        variants = validated_data.pop("variants", [])
        request = self.context["request"]
        item = ListingProfile.objects.create(**validated_data)
        self._save_variants(item, variants, request.user.tenant_id)
        return item

    def update(self, instance, validated_data):
        variants = validated_data.pop("variants", None)
        item = super().update(instance, validated_data)
        if variants is not None:
            self._save_variants(item, variants, self.context["request"].user.tenant_id, replace=True)
        return item

    @staticmethod
    def _save_variants(profile, variants, tenant_id, replace=False):
        if replace:
            profile.variants.all().delete()
        for raw in variants:
            sku = raw.get("sku")
            if not sku or sku.tenant_id != tenant_id or sku.spu_id != profile.product_id:
                raise serializers.ValidationError({"variants": "Each SKU must belong to the selected tenant and SPU."})
            seller_sku = raw.get("seller_sku") or sku.sku_code
            ListingVariant.objects.update_or_create(
                profile=profile,
                seller_sku=seller_sku,
                defaults={
                    "sku": sku,
                    "price": raw.get("price", sku.purchase_price or 0),
                    "stock_quantity": raw.get("stock_quantity", 0),
                    "attributes": raw.get("attributes", {}),
                    "external_variant_id": raw.get("external_variant_id", ""),
                    "is_enabled": raw.get("is_enabled", True),
                },
            )


class ListingPublicationJobSerializer(serializers.ModelSerializer):
    task_id = serializers.SerializerMethodField()

    class Meta:
        model = ListingPublicationJob
        fields = "__all__"

    def get_task_id(self, obj):
        task = getattr(obj, "listing_task", None)
        return task.id if task else None


class PlatformCategoryMappingSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source="platform.name", read_only=True)

    class Meta:
        model = PlatformCategoryMapping
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        tenant_id = self.context["request"].user.tenant_id
        platform = attrs.get("platform")
        if platform is not None and platform.tenant_id != tenant_id:
            raise serializers.ValidationError({"platform": "Platform must belong to the current tenant."})
        return attrs


class ListingAttributeMappingSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    template_name = serializers.CharField(source="template.name", read_only=True, allow_null=True)

    class Meta:
        model = ListingAttributeMapping
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        tenant_id = self.context["request"].user.tenant_id
        for field in ("platform", "template"):
            obj = attrs.get(field)
            if obj is not None and obj.tenant_id != tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        return attrs


class ListingTaskStepLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingTaskStepLog
        fields = "__all__"
        read_only_fields = ("tenant", "created_at")


class ListingTaskErrorLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingTaskErrorLog
        fields = "__all__"
        read_only_fields = ("tenant", "created_at", "resolved_at", "resolved_by")


class ListingTaskSerializer(serializers.ModelSerializer):
    profile_no = serializers.CharField(source="profile.profile_no", read_only=True, allow_null=True)
    steps = ListingTaskStepLogSerializer(source="step_logs", many=True, read_only=True)
    errors = ListingTaskErrorLogSerializer(source="error_logs", many=True, read_only=True)

    class Meta:
        model = ListingTask
        fields = "__all__"
        read_only_fields = ("tenant", "requested_by", "created_at", "updated_at", "started_at", "finished_at")
