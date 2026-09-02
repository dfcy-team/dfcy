from rest_framework import serializers

from .models import ListingProfile, ListingPublicationJob, ListingTemplate, ListingVariant, PlatformProductDetail


class ListingTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingTemplate
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "created_at", "updated_at")

    def validate_platform(self, value):
        if value.tenant_id != self.context["request"].user.tenant_id:
            raise serializers.ValidationError("Platform must belong to the current tenant.")
        return value


class ListingVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingVariant
        fields = "__all__"
        read_only_fields = ("profile",)


class ListingProfileSerializer(serializers.ModelSerializer):
    variants = ListingVariantSerializer(many=True, read_only=True)

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


class ListingPublicationJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingPublicationJob
        fields = "__all__"


class PlatformProductDetailSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    platform_code = serializers.CharField(source="platform.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    site_code = serializers.CharField(source="site.code", read_only=True, allow_null=True)
    site_name = serializers.CharField(source="site.name", read_only=True, allow_null=True)
    country_code = serializers.CharField(source="site.country_code", read_only=True, allow_null=True)
    internal_sku_code = serializers.CharField(source="internal_sku.sku_code", read_only=True)
    internal_legacy_sku_code = serializers.CharField(source="internal_sku.legacy_sku_code", read_only=True)

    class Meta:
        model = PlatformProductDetail
        fields = (
            "id", "tenant", "platform", "platform_name", "platform_code", "store", "store_name", "store_code",
            "site", "site_code", "site_name", "country_code", "platform_product_id", "platform_variant_id", "platform_sku", "source_old_sku_code",
            "internal_sku", "internal_sku_code", "internal_legacy_sku_code", "title", "variant",
            "category_l1", "category_l2", "category_l3", "sku_prefix", "shop_abbr", "sales_status",
            "owner", "leader", "platform_created_at", "platform_updated_at", "source", "created_at", "updated_at",
        )
        read_only_fields = ("tenant", "created_at", "updated_at", "source")

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(request.user, "tenant", None) if request else None
        platform = attrs.get("platform", getattr(self.instance, "platform", None))
        store = attrs.get("store", getattr(self.instance, "store", None))
        site = attrs.get("site", getattr(self.instance, "site", None))
        internal_sku = attrs.get("internal_sku", getattr(self.instance, "internal_sku", None))
        errors = {}
        old_code = attrs.get("source_old_sku_code", getattr(self.instance, "source_old_sku_code", ""))
        if not old_code and internal_sku is None:
            errors["source_old_sku_code"] = "旧 SKU 编码和新 SKU 编码必须至少提供一个。"
        if tenant:
            for name, value in (("platform", platform), ("store", store), ("site", site), ("internal_sku", internal_sku)):
                if value is not None and value.tenant_id != tenant.id:
                    errors[name] = "引用记录必须属于当前租户。"
        if store and platform and store.platform_id != platform.id:
            errors["store"] = "店铺所属平台与平台商品不一致。"
        if site and store:
            if (site.country_code or "").casefold() != (store.country_code or "").casefold():
                errors["site"] = "站点国家与店铺国家不一致。"
            values = {(platform.code or "").casefold(), (platform.name or "").casefold(), (platform.platform_type or "").casefold()}
            if site.platform and site.platform.casefold() not in values:
                errors["site"] = "站点所属平台与平台商品不一致。"
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class PlatformProductDetailBulkUpdateSerializer(serializers.Serializer):
    """Validate a tenant-scoped platform-detail bulk edit request."""

    match_type = serializers.ChoiceField(choices=("old_spu", "new_spu", "legacy_spu", "spu"))
    spu_code = serializers.CharField(max_length=120, allow_blank=False, trim_whitespace=True)
    ids = serializers.ListField(child=serializers.JSONField(), required=False, allow_empty=True)
    fields = serializers.DictField(required=False, default=dict)
    preview = serializers.BooleanField(required=False, default=False)

    SAFE_FIELDS = {
        "title", "variant", "sales_status", "owner", "leader", "platform_sku",
        "platform_product_id", "platform_variant_id", "source_old_sku_code", "new_sku_code", "internal_sku",
    }

    def validate_fields(self, value):
        unknown = set(value) - self.SAFE_FIELDS
        if unknown:
            raise serializers.ValidationError({field: "该字段不支持批量修改。" for field in sorted(unknown)})
        cleaned = {}
        for field, raw in value.items():
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            cleaned[field] = raw.strip() if isinstance(raw, str) else raw
        return cleaned

    def validate(self, attrs):
        attrs["match_type"] = {"legacy_spu": "old_spu", "spu": "new_spu"}.get(attrs["match_type"], attrs["match_type"])
        return attrs
