import re

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    ProductBundleComponent,
    ProductCategory,
    ProductColor,
    ProductAttribute,
    ProductResearch,
    ProductLifecycleDecision,
    ProductLifecycleReview,
    ProductLifecycleStage,
    ProductLegacyItem,
    ProductSKU,
    ProductSPU,
    ProductStatusRecommendation,
    ProductStatusSnapshot,
    ProductStatusTransition,
)
from .coding_services import (
    SEASON_CODES,
    allocate_legacy_sku_code,
    allocate_spu_code,
    build_sku_code,
    category_path,
)
from apps.masterdata.models import CountrySiteMaster


class ProductCategorySerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductCategory
        fields = (
            "id", "tenant_id", "parent", "level", "code", "name", "english_name",
            "platform_category_id", "spec_dimensions", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def validate_parent(self, value):
        if value and value.tenant_id != self.context["request"].user.tenant_id:
            raise serializers.ValidationError("Parent category does not belong to current tenant.")
        return value

    def validate_spec_dimensions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Specification dimensions must be a list.")
        codes = []
        for item in value:
            if not isinstance(item, dict) or not item.get("code") or not item.get("name"):
                raise serializers.ValidationError("Each dimension requires code and name.")
            codes.append(item["code"])
        if len(codes) != len(set(codes)):
            raise serializers.ValidationError("Specification dimension codes must be unique.")
        return value

    def validate(self, attrs):
        level = attrs.get("level", getattr(self.instance, "level", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if self.instance:
            immutable = ("parent", "level", "code")
            changed = [field for field in immutable if field in attrs and attrs[field] != getattr(self.instance, field)]
            if changed:
                raise serializers.ValidationError({field: "Category hierarchy codes are immutable." for field in changed})
            if (
                "spec_dimensions" in attrs
                and attrs["spec_dimensions"] != self.instance.spec_dimensions
                and self.instance.products.exists()
            ):
                old_codes = [item.get("code") for item in (self.instance.spec_dimensions or [])]
                new_codes = [item.get("code") for item in attrs["spec_dimensions"]]
                has_skus = ProductSKU.objects.filter(spu__category_node=self.instance).exists()
                if has_skus and old_codes != new_codes:
                    raise serializers.ValidationError({"spec_dimensions": "Specification structure cannot change after an SKU is generated."})
        return attrs


class ProductColorSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductColor
        fields = ("id", "tenant_id", "code", "name", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def validate(self, attrs):
        if self.instance and "code" in attrs and attrs["code"] != self.instance.code:
            if ProductSKU.objects.filter(tenant=self.instance.tenant, color_code=self.instance.code).exists():
                raise serializers.ValidationError({"code": "Color code cannot change after it is used by an SKU."})
        return attrs


class ProductAttributeSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductAttribute
        fields = ("id", "tenant_id", "code", "name", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "tenant_id", "code", "created_at", "updated_at")


class ProductResearchSerializer(serializers.ModelSerializer):
    CONTROLLED_UPDATE_FIELDS = {"approval_status"}

    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    category_name = serializers.CharField(source="category_node.name", read_only=True, allow_null=True)
    target_site_ids = serializers.SerializerMethodField()

    class Meta:
        model = ProductResearch
        fields = (
            "id",
            "tenant_id",
            "research_no",
            "product_name",
            "platform",
            "category_node",
            "category_name",
            "target_sites",
            "target_site_ids",
            "competitor_url",
            "estimated_sales",
            "estimated_gross_margin",
            "risk_points",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance is not None:
            attempted = self.CONTROLLED_UPDATE_FIELDS.intersection(self.initial_data)
            if attempted:
                raise serializers.ValidationError(
                    {field: "This status can only be changed through an authorized workflow action." for field in attempted}
                )
        return attrs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        self.fields["category_node"].queryset = ProductCategory.objects.filter(tenant_id=tenant_id) if tenant_id else ProductCategory.objects.none()
        self.fields["target_sites"].queryset = CountrySiteMaster.objects.filter(tenant_id=tenant_id) if tenant_id else CountrySiteMaster.objects.none()

    def to_internal_value(self, data):
        if "target_site_ids" in data and "target_sites" not in data:
            data = data.copy()
            data["target_sites"] = data.get("target_site_ids")
        return super().to_internal_value(data)

    def get_target_site_ids(self, obj):
        return list(obj.target_sites.values_list("id", flat=True))

    def validate_category_node(self, value):
        if value is not None:
            request = self.context["request"]
            if value.tenant_id != request.user.tenant_id:
                raise serializers.ValidationError("Category does not belong to current tenant.")
            if not value.is_active:
                raise serializers.ValidationError("An active product category is required.")
        return value

    def validate_target_sites(self, value):
        request = self.context["request"]
        if any(site.tenant_id != request.user.tenant_id or site.status != "active" for site in value):
            raise serializers.ValidationError("Only active country sites in the current tenant may be selected.")
        return value


class ProductSPUSerializer(serializers.ModelSerializer):
    CONTROLLED_UPDATE_FIELDS = {"lifecycle_status", "sales_status"}

    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    sales_status_display = serializers.CharField(source="get_sales_status_display", read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["sales_status_display"] = {
            ProductSPU.SalesStatus.NOT_LISTED: "未上架",
            ProductSPU.SalesStatus.ON_SALE: "在售",
            ProductSPU.SalesStatus.PAUSED: "已暂停",
            ProductSPU.SalesStatus.STOPPED: "已停止",
        }.get(instance.sales_status, instance.get_sales_status_display())
        return data
    sku_codes = serializers.SerializerMethodField()
    sku_count = serializers.SerializerMethodField()

    def get_sku_codes(self, obj):
        return [sku.sku_code for sku in obj.skus.all()]

    def get_sku_count(self, obj):
        return obj.skus.count()

    class Meta:
        model = ProductSPU
        fields = (
            "id",
            "tenant_id",
            "spu_code",
            "legacy_spu_code",
            "sku_codes",
            "sku_count",
            "product_name",
            "brand",
            "category",
            "category_node",
            "product_type",
            "l1_code",
            "l2_code",
            "l3_code",
            "season_code",
            "lifecycle_status",
            "sales_status",
            "sales_status_display",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "lifecycle_status",
            "sales_status",
            "is_code_frozen",
            "l1_code",
            "l2_code",
            "l3_code",
            "created_at",
            "updated_at",
        )
        extra_kwargs = {"spu_code": {"required": False, "allow_blank": False}}

    def validate_category_node(self, value):
        if value and value.tenant_id != self.context["request"].user.tenant_id:
            raise serializers.ValidationError("Category does not belong to current tenant.")
        if value and not value.is_active:
            raise serializers.ValidationError("An active product category is required.")
        if value:
            try:
                category_path(value)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is not None:
            attempted = self.CONTROLLED_UPDATE_FIELDS.intersection(self.initial_data)
            if attempted:
                raise serializers.ValidationError(
                    {field: "This status can only be changed through an authorized workflow action." for field in attempted}
                )
        if instance and instance.is_code_frozen and "spu_code" in attrs and attrs["spu_code"] != instance.spu_code:
            raise serializers.ValidationError({"spu_code": "Code is frozen and cannot be changed."})
        if instance and "season_code" in attrs and attrs["season_code"] != instance.season_code:
            raise serializers.ValidationError("Attribute code is immutable after SPU creation.")
        if instance is None and not self.initial_data.get("spu_code"):
            attrs["season_code"] = str(attrs.get("season_code") or "0")
            if not attrs.get("category_node"):
                raise serializers.ValidationError({"category_node": "Category is required for automatic coding."})
            if not re.fullmatch(r"[0-9]", str(attrs.get("season_code") or "")):
                raise serializers.ValidationError({"season_code": "Attribute code must be one digit."})
            try:
                category_path(attrs["category_node"])
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"category_node": exc.messages}) from exc
        return attrs

    def update(self, instance, validated_data):
        category = validated_data.get("category_node")
        if category and category.pk != instance.category_node_id:
            # Reclassification changes business ownership only; generated identifiers remain stable.
            validated_data["category"] = category.name
        return super().update(instance, validated_data)

    def create(self, validated_data):
        if not validated_data.get("spu_code"):
            tenant = validated_data["tenant"]
            try:
                code, segments = allocate_spu_code(
                    tenant=tenant,
                    category=validated_data["category_node"],
                    season_code=validated_data["season_code"],
                )
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"spu_code": exc.messages}) from exc
            validated_data["spu_code"] = code
            validated_data["l1_code"], validated_data["l2_code"], validated_data["l3_code"] = segments
            validated_data["category"] = validated_data["category_node"].name
        return super().create(validated_data)


class ProductSKUSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductSKU
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku_code",
            "legacy_sku_code",
            "product_name",
            "color_code",
            "specification",
            "spec_values",
            "size",
            "material",
            "selling_points",
            "package_weight",
            "package_volume",
            "purchase_price",
            "unit",
            "image_url",
            "package_length_cm",
            "package_width_cm",
            "package_height_cm",
            "origin_country",
            "hs_code",
            "product_description",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "is_code_frozen", "created_at", "updated_at")
        extra_kwargs = {
            "sku_code": {"required": False, "allow_blank": False},
            "specification": {"read_only": True},
        }

    def validate_spu(self, value):
        request = self.context["request"]
        if value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("SPU does not belong to current tenant.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_code_frozen and "sku_code" in attrs and attrs["sku_code"] != instance.sku_code:
            raise serializers.ValidationError({"sku_code": "Code is frozen and cannot be changed."})
        if instance and any(field in attrs for field in ("spu", "color_code", "spec_values")):
            raise serializers.ValidationError("SPU, color and specification are immutable after SKU creation.")
        if instance is None and not self.initial_data.get("sku_code"):
            if not attrs.get("spu") or not attrs.get("color_code"):
                raise serializers.ValidationError("SPU and color are required for automatic coding.")
            color_exists = ProductColor.objects.filter(
                tenant=self.context["request"].user.tenant,
                code=attrs["color_code"],
                is_active=True,
            ).exists()
            if not color_exists:
                raise serializers.ValidationError({"color_code": "Select an active color from the current tenant dictionary."})
            spec_values = attrs.get("spec_values", {})
            if not isinstance(spec_values, dict):
                raise serializers.ValidationError({"spec_values": "Specifications must be keyed by dimension code."})
            dimensions = attrs["spu"].category_node.spec_dimensions or []
            expected = {item.get("code") for item in dimensions if item.get("code")}
            extra = set(spec_values) - expected if expected else set(spec_values) - {"spec"}
            if extra:
                raise serializers.ValidationError(
                    {"spec_values": f"Unknown specification dimensions: {', '.join(sorted(extra))}."}
                )
        return attrs

    def create(self, validated_data):
        if not validated_data.get("sku_code"):
            spu = validated_data["spu"]
            spec_values = {
                str(code): str(value or "").strip()
                for code, value in (validated_data.get("spec_values") or {}).items()
                if str(value or "").strip() not in ("", "0")
            }
            if spec_values:
                category = spu.category_node
                category.refresh_from_db(fields=["spec_dimensions", "updated_at"])
                dimensions = [dict(item) for item in (category.spec_dimensions or [])]
                if not dimensions:
                    dimensions = [
                        {"code": code, "name": "���" if index == 0 else code, "values": []}
                        for index, code in enumerate(spec_values)
                    ]
                by_code = {item.get("code"): item for item in dimensions}
                for code, value in spec_values.items():
                    if code not in by_code:
                        raise serializers.ValidationError({"spec_values": f"Unknown specification dimension: {code}."})
                    values = list(by_code[code].get("values") or [])
                    if value not in values:
                        values.append(value)
                        by_code[code]["values"] = values
                category.spec_dimensions = dimensions
                category.save(update_fields=["spec_dimensions", "updated_at"])
                spu.category_node = category
            sku_code, specification, normalized = build_sku_code(
                spu=spu,
                color_code=validated_data["color_code"],
                spec_values=spec_values,
            )
            legacy_sku_code = str(validated_data.get("legacy_sku_code") or "").strip()
            if legacy_sku_code:
                sku_code = allocate_legacy_sku_code(
                    tenant=validated_data["tenant"],
                    base_code=sku_code,
                    legacy_sku_code=legacy_sku_code,
                )
            validated_data["sku_code"] = sku_code
            validated_data["specification"] = specification
            validated_data["spec_values"] = normalized
            validated_data["size"] = specification
        return super().create(validated_data)


class ProductLegacyItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category_node.name", read_only=True)
    generated_spu_code = serializers.CharField(source="generated_spu.spu_code", read_only=True)
    generated_sku_code = serializers.CharField(source="generated_sku.sku_code", read_only=True)

    class Meta:
        model = ProductLegacyItem
        fields = ("id", "legacy_spu_code", "legacy_sku_code", "product_name", "category_node", "category_name",
                  "attribute_code", "color_code", "specification", "purchase_price", "unit", "image_url",
                  "package_weight", "package_volume", "package_length_cm", "package_width_cm", "package_height_cm",
                  "origin_country", "hs_code", "product_description", "status", "generated_spu_code",
                  "generated_sku_code", "error_message", "created_at", "updated_at")
        read_only_fields = ("id", "status", "generated_spu_code", "generated_sku_code", "error_message", "created_at", "updated_at")


class ProductDetailRowSerializer(serializers.Serializer):
    """Flat row contract consumed by the 商品明细数据 page.

    The page intentionally combines pending legacy import rows and generated
    SKU rows.  Keeping a dedicated serializer for that read model means the
    collection endpoint can paginate the combined result without exposing
    implementation details of either staging model.
    """

    id = serializers.IntegerField()
    row_type = serializers.ChoiceField(choices=("legacy", "sku"))
    legacy_spu_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    legacy_sku_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    spu_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    sku_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    product_name = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    category_node = serializers.IntegerField(allow_null=True, required=False)
    category_name = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    color_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    specification = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    purchase_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        allow_null=True,
        required=False,
        coerce_to_string=True,
    )
    attribute_code = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    status = serializers.CharField()
    status_name = serializers.CharField()
    error_message = serializers.CharField(allow_blank=True, allow_null=True, required=False)


class ProductBundleComponentSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    component_sku_code = serializers.CharField(source="component_sku.sku_code", read_only=True)
    component_product_name = serializers.CharField(source="component_sku.spu.product_name", read_only=True)

    class Meta:
        model = ProductBundleComponent
        fields = (
            "id", "tenant_id", "bundle_sku", "component_sku", "component_sku_code",
            "component_product_name", "quantity", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def validate(self, attrs):
        tenant_id = self.context["request"].user.tenant_id
        bundle_sku = attrs.get("bundle_sku", getattr(self.instance, "bundle_sku", None))
        component_sku = attrs.get("component_sku", getattr(self.instance, "component_sku", None))
        if bundle_sku and bundle_sku.tenant_id != tenant_id:
            raise serializers.ValidationError({"bundle_sku": "Bundle SKU does not belong to current tenant."})
        if component_sku and component_sku.tenant_id != tenant_id:
            raise serializers.ValidationError({"component_sku": "Component SKU does not belong to current tenant."})
        if bundle_sku and bundle_sku.spu.product_type != ProductSPU.ProductType.BUNDLE:
            raise serializers.ValidationError({"bundle_sku": "SKU must belong to a bundle product."})
        if component_sku and component_sku.spu.product_type == ProductSPU.ProductType.BUNDLE:
            raise serializers.ValidationError({"component_sku": "Nested bundles are not supported."})
        if bundle_sku and component_sku and bundle_sku.id == component_sku.id:
            raise serializers.ValidationError({"component_sku": "A bundle cannot contain itself."})
        return attrs


class ProductStatusSnapshotSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductStatusSnapshot
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "source",
            "source_reference",
            "metrics_payload",
            "calculated_status",
            "calculated_at",
        )
        read_only_fields = fields


class ProductStatusRecommendationSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    source_snapshot = ProductStatusSnapshotSerializer(read_only=True)
    confirmed_by_id = serializers.IntegerField(source="confirmed_by.id", read_only=True)

    class Meta:
        model = ProductStatusRecommendation
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "recommended_status",
            "reason_code",
            "reason_detail",
            "confidence",
            "source_snapshot",
            "status",
            "created_at",
            "confirmed_by_id",
            "confirmed_at",
        )
        read_only_fields = fields


class ProductStatusTransitionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    approved_by_id = serializers.IntegerField(source="approved_by.id", read_only=True)

    class Meta:
        model = ProductStatusTransition
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "from_status",
            "to_status",
            "trigger_type",
            "recommendation",
            "approved_by_id",
            "reason",
            "created_at",
        )
        read_only_fields = fields


class ProductLifecycleReviewSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    reviewed_by_id = serializers.IntegerField(source="reviewed_by.id", read_only=True)

    class Meta:
        model = ProductLifecycleReview
        fields = (
            "id", "tenant_id", "spu", "sku", "current_stage", "recommended_stage",
            "review_period_start", "review_period_end", "reason_code", "reason_detail",
            "confidence", "source_metrics", "source_type", "rule_version", "status",
            "reviewed_by_id", "reviewed_at", "created_at", "updated_at",
        )
        read_only_fields = fields


class ProductLifecycleDecisionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = ProductLifecycleDecision
        fields = ("id", "tenant_id", "review", "decision", "from_stage", "to_stage", "actor_id", "reason", "created_at")
        read_only_fields = fields


class ProductLifecycleEvaluationSerializer(serializers.Serializer):
    spu_id = serializers.IntegerField(min_value=1, required=False)
    sku_id = serializers.IntegerField(min_value=1, required=False)
    current_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices)
    recommended_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices)
    review_period_start = serializers.DateField()
    review_period_end = serializers.DateField()
    reason_code = serializers.CharField(max_length=80)
    reason_detail = serializers.CharField(max_length=2000)
    confidence = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=0, max_value=1)
    source_metrics = serializers.JSONField()

    def validate(self, attrs):
        if not attrs.get("spu_id") and not attrs.get("sku_id"):
            raise serializers.ValidationError("spu_id or sku_id is required.")
        if attrs["review_period_start"] > attrs["review_period_end"]:
            raise serializers.ValidationError({"review_period_end": "Must not be earlier than review_period_start."})
        return attrs


class ProductLifecycleDecisionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class ProductLifecycleQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    status = serializers.ChoiceField(choices=ProductLifecycleReview.Status.choices, required=False)
    recommended_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices, required=False)
