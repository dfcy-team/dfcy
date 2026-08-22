from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.products.coding_services import category_path
from apps.products.models import ProductCategory

from .models import (
    DevelopmentCostEstimate,
    DevelopmentProductArchive,
    DevelopmentProductArchiveEvent,
    DevelopmentProject,
    ProductSalesSummary,
)


class DevelopmentProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentProject
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "stage", "finalized_product", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        self.fields["category_node"].queryset = (
            ProductCategory.objects.filter(tenant_id=tenant_id, is_active=True, level=ProductCategory.Level.L3)
            if tenant_id
            else ProductCategory.objects.none()
        )

    def validate(self, attrs):
        request = self.context["request"]
        for field in ("requirement", "supplier", "assigned_to"):
            value = attrs.get(field)
            if value is not None and value.tenant_id != request.user.tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        category = attrs.get("category_node")
        if category is not None:
            if category.tenant_id != request.user.tenant_id or not category.is_active or category.level != ProductCategory.Level.L3:
                raise serializers.ValidationError({"category_node": "An active tenant-owned L3 category is required."})
            attrs["category"] = category.name
        return attrs


class DevelopmentCostEstimateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentCostEstimate
        fields = "__all__"
        read_only_fields = ("total_cost", "estimated_margin", "estimated_margin_rate", "status", "approved_by", "created_at")


class ProductSalesSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSalesSummary
        fields = "__all__"


class DevelopmentProductArchiveEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)
    actor_name = serializers.CharField(source="actor.get_full_name", read_only=True)

    class Meta:
        model = DevelopmentProductArchiveEvent
        fields = ("id", "action", "from_status", "to_status", "metadata", "actor_id", "actor_name", "created_at")
        read_only_fields = fields


class DevelopmentProductArchiveSerializer(serializers.ModelSerializer):
    project_no = serializers.CharField(source="project.project_no", read_only=True)
    project_id = serializers.IntegerField(read_only=True)
    project_stage = serializers.CharField(source="project.stage", read_only=True)
    project_status = serializers.CharField(source="project.status", read_only=True)
    target_sites = serializers.ListField(source="project.target_sites", read_only=True)
    formal_spu_code = serializers.CharField(source="formal_product.spu_code", read_only=True, allow_null=True)
    formal_product_id = serializers.IntegerField(read_only=True, allow_null=True)
    trial_spu_code = serializers.CharField(source="trial_product.spu_code", read_only=True, allow_null=True)
    trial_product_id = serializers.IntegerField(read_only=True, allow_null=True)
    trial_sku_code = serializers.CharField(source="trial_sku.sku_code", read_only=True, allow_null=True)
    trial_sku_id = serializers.IntegerField(read_only=True, allow_null=True)
    formal_sku_code = serializers.CharField(source="formal_sku.sku_code", read_only=True, allow_null=True)
    formal_sku_id = serializers.IntegerField(read_only=True, allow_null=True)
    platform_code = serializers.CharField(source="platform_master.code", read_only=True, allow_null=True)
    platform_name = serializers.CharField(source="platform_master.name", read_only=True, allow_null=True)
    store_code = serializers.CharField(source="store_master.code", read_only=True, allow_null=True)
    store_name = serializers.CharField(source="store_master.name", read_only=True, allow_null=True)
    store_country_code = serializers.CharField(source="store_master.country_code", read_only=True, allow_null=True)
    # ``platform_id``/``store_id`` are accepted as aliases for callers that
    # consume the master-data API's naming convention.
    platform_id = serializers.PrimaryKeyRelatedField(
        source="platform_master",
        queryset=PlatformMaster.objects.none(),
        required=False,
        write_only=True,
    )
    store_id = serializers.PrimaryKeyRelatedField(
        source="store_master",
        queryset=StoreMaster.objects.none(),
        required=False,
        write_only=True,
    )
    category_name = serializers.CharField(source="category_node.name", read_only=True, allow_null=True)
    category_level = serializers.IntegerField(source="category_node.level", read_only=True, allow_null=True)
    category_path = serializers.SerializerMethodField()
    is_virtual = serializers.BooleanField(read_only=True)
    events = DevelopmentProductArchiveEventSerializer(many=True, read_only=True)

    class Meta:
        model = DevelopmentProductArchive
        fields = (
            "id", "tenant", "project", "project_id", "project_no", "project_stage", "project_status",
            "target_sites", "archive_no", "product_name", "development_spu_code", "season_code", "category", "category_node", "category_name",
            "category_level", "category_path", "platform_master", "platform_id", "platform_code", "platform_name",
            "store_master", "store_id", "store_code", "store_name", "store_country_code", "platform", "site",
            "inventory_mode", "virtual_inventory_sku", "virtual_inventory_qty", "test_result", "test_notes", "status",
            "formal_product", "formal_product_id", "formal_spu_code", "formal_sku_id", "formal_sku_code",
            "trial_product_id", "trial_spu_code", "trial_sku_id", "trial_sku_code", "trial_confirmed_at", "formalized_at", "is_virtual",
            "created_at", "updated_at", "events",
        )
        read_only_fields = (
            "id", "tenant", "archive_no", "inventory_mode", "virtual_inventory_sku", "status",
            "formal_product", "formal_spu_code", "formal_sku_id", "formal_sku_code", "trial_product_id", "trial_spu_code", "trial_sku_id", "trial_sku_code",
            "platform_code", "platform_name", "store_code", "store_name", "store_country_code",
            "development_spu_code", "season_code", "trial_confirmed_at", "formalized_at", "created_at",
            "updated_at", "events",
        )
        extra_kwargs = {
            "product_name": {"required": False},
            "category": {"required": False, "allow_blank": True},
            "platform": {"required": False},
            "site": {"required": False},
            "platform_master": {"required": False, "allow_null": True},
            "store_master": {"required": False, "allow_null": True},
            "virtual_inventory_qty": {"required": False, "min_value": 0},
            "test_notes": {"required": False, "allow_blank": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        self.fields["category_node"].queryset = (
            ProductCategory.objects.filter(tenant_id=tenant_id, is_active=True, level=ProductCategory.Level.L3)
            if tenant_id
            else ProductCategory.objects.none()
        )
        self.fields["platform_master"].queryset = (
            PlatformMaster.objects.filter(tenant_id=tenant_id, status=StatusChoices.ACTIVE)
            if tenant_id
            else PlatformMaster.objects.none()
        )
        self.fields["store_master"].queryset = (
            StoreMaster.objects.select_related("platform").filter(tenant_id=tenant_id, status=StatusChoices.ACTIVE)
            if tenant_id
            else StoreMaster.objects.none()
        )
        # Alias fields share the same tenant/active querysets.
        self.fields["platform_id"].queryset = self.fields["platform_master"].queryset
        self.fields["store_id"].queryset = self.fields["store_master"].queryset

    def validate_project(self, value):
        request = self.context.get("request")
        if request is not None and value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Project must belong to the current tenant.")
        return value

    def validate_category_node(self, value):
        request = self.context.get("request")
        if value is None or request is None or value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Category must belong to the current tenant.")
        if not value.is_active or value.level != ProductCategory.Level.L3:
            raise serializers.ValidationError("An active L3 leaf category is required.")
        try:
            category_path(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        if self.instance is not None and "project" in attrs and attrs["project"].pk != self.instance.project_id:
            raise serializers.ValidationError({"project": "The development project cannot change."})
        if self.instance is not None and self.instance.status != DevelopmentProductArchive.Status.TRIAL:
            attempted = {
                "product_name", "category_node", "platform", "site", "platform_master", "platform_id",
                "store_master", "store_id", "virtual_inventory_qty", "test_notes",
            }.intersection(self.initial_data)
            if attempted:
                raise serializers.ValidationError({field: "Only a virtual trial archive can be edited." for field in attempted})
        if self.instance is not None and self.instance.trial_product_id:
            attempted_codes = {"development_spu_code", "season_code"}.intersection(self.initial_data)
            if attempted_codes:
                raise serializers.ValidationError({field: "Development coding is immutable after trial generation." for field in attempted_codes})
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        current_platform = getattr(self.instance, "platform_master", None)
        current_store = getattr(self.instance, "store_master", None)
        platform = attrs.get("platform_master", current_platform)
        store = attrs.get("store_master", current_store)
        if platform is not None:
            if platform.tenant_id != tenant_id or platform.status != StatusChoices.ACTIVE:
                raise serializers.ValidationError({"platform_master": "Platform must be active and belong to the current tenant."})
        if store is not None:
            if store.tenant_id != tenant_id or store.status != StatusChoices.ACTIVE:
                raise serializers.ValidationError({"store_master": "Store must be active and belong to the current tenant."})
            if platform is None:
                platform = store.platform
                attrs["platform_master"] = platform
                if platform.tenant_id != tenant_id or platform.status != StatusChoices.ACTIVE:
                    raise serializers.ValidationError({"platform_master": "Platform must be active and belong to the current tenant."})
            if store.platform_id != platform.id:
                raise serializers.ValidationError({"store_master": "Store must belong to the selected platform."})
            supplied_site = attrs.get("site", getattr(self.instance, "site", ""))
            if supplied_site and str(supplied_site).strip().lower() not in {"internal", str(store.country_code).strip().lower()}:
                raise serializers.ValidationError({"site": "Site must match the selected store country."})
            attrs["site"] = str(store.country_code).strip().upper()
        if platform is not None:
            supplied_platform = attrs.get("platform", getattr(self.instance, "platform", ""))
            if supplied_platform and str(supplied_platform).strip().lower() not in {"internal", str(platform.code).strip().lower()}:
                raise serializers.ValidationError({"platform": "Platform snapshot must match the selected platform."})
            attrs["platform"] = str(platform.code).strip()
        project = attrs.get("project") or getattr(self.instance, "project", None)
        category = attrs.get("category_node") or getattr(project, "category_node", None) or getattr(self.instance, "category_node", None)
        if category is None:
            raise serializers.ValidationError({"category_node": "An active L3 product category is required."})
        self.validate_category_node(category)
        attrs["category_node"] = category
        attrs["category"] = category.name
        return attrs

    def get_category_path(self, obj):
        category = getattr(obj, "category_node", None)
        if category is None:
            return ""
        parts = []
        while category is not None:
            parts.append(f"L{category.level} {category.code} {category.name}")
            category = category.parent
        return " / ".join(reversed(parts))


class DevelopmentProductArchiveConfirmationSerializer(serializers.Serializer):
    test_result = serializers.ChoiceField(
        choices=DevelopmentProductArchive.TestResult.choices,
        required=False,
        default=DevelopmentProductArchive.TestResult.PASS,
    )
    test_notes = serializers.CharField(required=False, allow_blank=True, max_length=10000)
