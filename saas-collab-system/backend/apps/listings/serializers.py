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
    PlatformProductDetail,
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


class PlatformProductDetailSerializer(serializers.ModelSerializer):
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    platform_code = serializers.CharField(source="platform.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    site_code = serializers.CharField(source="site.code", read_only=True, allow_null=True)
    site_name = serializers.CharField(source="site.name", read_only=True, allow_null=True)
    country_code = serializers.CharField(source="site.country_code", read_only=True, allow_null=True)
    internal_sku_code = serializers.CharField(source="internal_sku.sku_code", read_only=True, allow_null=True)
    internal_legacy_sku_code = serializers.CharField(source="internal_sku.legacy_sku_code", read_only=True, allow_null=True)
    mapping = serializers.SerializerMethodField()

    class Meta:
        model = PlatformProductDetail
        fields = (
            "id", "tenant", "platform", "platform_name", "platform_code", "store", "store_name", "store_code",
            "site", "site_code", "site_name", "country_code", "platform_product_id", "platform_variant_id", "platform_sku", "source_old_sku_code",
            "internal_sku", "internal_sku_code", "internal_legacy_sku_code", "title", "variant",
            "category_l1", "category_l2", "category_l3", "sku_prefix", "shop_abbr", "sales_status",
            "owner", "leader", "platform_created_at", "platform_updated_at", "source", "created_at", "updated_at",
            "mapping",
        )
        read_only_fields = ("tenant", "created_at", "updated_at", "source")

    def get_mapping(self, obj):
        """Expose mapping workflow state only inside its own permission scope."""

        request = self.context.get("request")
        user = getattr(request, "user", None)
        from apps.permissions.services import check_user_permission

        if not check_user_permission(user, "integrations.product_mapping.view"):
            return None
        prefetched_sentinel = object()
        prefetched = getattr(obj, "_authorized_marketplace_mapping", prefetched_sentinel)
        if prefetched is not prefetched_sentinel:
            # ``to_attr`` for a reverse OneToOne relation is a single model
            # instance (or None), while older queryset code may still hand us
            # a one-item list.  Handle both without falling back to an
            # unscoped reverse lookup when the authorized prefetch found no
            # visible relation.
            if isinstance(prefetched, (list, tuple)):
                mapping = prefetched[0] if prefetched else None
            else:
                mapping = prefetched
        else:
            try:
                mapping = obj.marketplace_mapping
            except Exception:  # reverse one-to-one is absent for unmapped details
                mapping = None
            if mapping is not None:
                from apps.integrations.models import MarketplaceProductMapping
                from apps.permissions.ui_p6_scopes import filter_product_mappings

                authorized = filter_product_mappings(
                    user,
                    MarketplaceProductMapping.objects.filter(
                        tenant=user.tenant,
                        pk=mapping.pk,
                    ),
                    "integrations.product_mapping.view",
                )
                if not authorized.exists():
                    return None
        if mapping is None:
            return None
        return {
            "id": mapping.id,
            "status": mapping.status,
            "sku_id": mapping.sku_id,
            "sku_code": mapping.sku.sku_code if mapping.sku_id and mapping.sku else None,
            "confidence": mapping.confidence,
            "result_code": mapping.result_code,
            "manually_confirmed": mapping.manually_confirmed,
        }

    def validate(self, attrs):
        request = self.context.get("request")
        tenant = getattr(request.user, "tenant", None) if request else None
        platform = attrs.get("platform", getattr(self.instance, "platform", None))
        store = attrs.get("store", getattr(self.instance, "store", None))
        site = attrs.get("site", getattr(self.instance, "site", None))
        internal_sku = attrs.get("internal_sku", getattr(self.instance, "internal_sku", None))
        errors = {}
        old_code = attrs.get("source_old_sku_code", getattr(self.instance, "source_old_sku_code", ""))
        # Manual creation/editing must retain a SKU mapping.  The dedicated
        # variant-ID import intentionally bypasses this serializer because it
        # only updates platform_product_id on an existing row.
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
