from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster
from apps.products.coding_services import category_path
from apps.products.models import ProductCategory

from .models import (
    DevelopmentCostEstimate,
    DevelopmentProject,
    DevelopmentProductArchive,
    DevelopmentProductArchiveEvent,
    DevelopmentRequirementCompetitorLink,
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
            ProductCategory.objects.filter(
                tenant_id=tenant_id,
                is_active=True,
                level=ProductCategory.Level.L3,
            )
            if tenant_id
            else ProductCategory.objects.none()
        )

    def validate_category_node(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        if request is not None and value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Category does not belong to current tenant.")
        if not value.is_active:
            raise serializers.ValidationError("An active product category is required.")
        if value.level != ProductCategory.Level.L3:
            raise serializers.ValidationError("Development products must use an active L3 leaf category.")
        try:
            category_path(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        request = self.context["request"]
        for field in ("requirement", "supplier", "assigned_to"):
            value = attrs.get(field)
            if value is not None and value.tenant_id != request.user.tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        category = attrs.get("category_node")
        requirement = attrs.get("requirement")
        if requirement is None and self.instance is not None:
            requirement = self.instance.requirement
        # A project created from a research requirement inherits its
        # structured category unless the operator explicitly overrides it.
        if category is None and requirement is not None:
            category = getattr(requirement, "category_node", None)
            if category is not None:
                attrs["category_node"] = category
        if category is not None:
            self.validate_category_node(category)
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
        fields = (
            "id",
            "action",
            "from_status",
            "to_status",
            "metadata",
            "actor_id",
            "actor_name",
            "created_at",
        )
        read_only_fields = fields


class DevelopmentProductArchiveSerializer(serializers.ModelSerializer):
    project_no = serializers.CharField(source="project.project_no", read_only=True)
    project_id = serializers.IntegerField(read_only=True)
    project_stage = serializers.CharField(source="project.stage", read_only=True)
    project_status = serializers.CharField(source="project.status", read_only=True)
    target_sites = serializers.ListField(source="project.target_sites", read_only=True)
    assigned_to_id = serializers.IntegerField(source="project.assigned_to_id", read_only=True)
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
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    updated_by_id = serializers.IntegerField(source="updated_by.id", read_only=True, allow_null=True)
    trial_confirmed_by_id = serializers.IntegerField(source="trial_confirmed_by.id", read_only=True, allow_null=True)
    formalized_by_id = serializers.IntegerField(source="formalized_by.id", read_only=True, allow_null=True)
    confirmed_by_id = serializers.IntegerField(source="trial_confirmed_by.id", read_only=True, allow_null=True)
    confirmed_at = serializers.DateTimeField(source="trial_confirmed_at", read_only=True, allow_null=True)
    converted_by_id = serializers.IntegerField(source="formalized_by.id", read_only=True, allow_null=True)
    converted_at = serializers.DateTimeField(source="formalized_at", read_only=True, allow_null=True)
    is_virtual = serializers.BooleanField(read_only=True)
    virtual_inventory = serializers.SerializerMethodField()
    events = DevelopmentProductArchiveEventSerializer(many=True, read_only=True)

    class Meta:
        model = DevelopmentProductArchive
        fields = (
            "id",
            "tenant",
            "project",
            "project_id",
            "project_no",
            "project_stage",
            "project_status",
            "target_sites",
            "archive_no",
            "product_name", "development_spu_code", "season_code", "category", "category_node", "category_name",
            "category_level", "category_path", "platform_master", "platform_id", "platform_code", "platform_name",
            "store_master", "store_id", "store_code", "store_name", "store_country_code", "platform", "site",
            "inventory_mode", "virtual_inventory_sku", "virtual_inventory_qty", "test_result", "test_notes", "status",
            "formal_product", "formal_product_id", "formal_spu_code", "formal_sku_id", "formal_sku_code",
            "trial_product_id", "trial_spu_code", "trial_sku_id", "trial_sku_code", "trial_confirmed_by_id",
            "trial_confirmed_at", "formalized_by_id", "formalized_at", "confirmed_by_id", "confirmed_at",
            "converted_by_id", "converted_at", "is_virtual", "virtual_inventory", "assigned_to_id", "created_by_id",
            "updated_by_id", "created_at", "updated_at", "events",
        )
        read_only_fields = (
            "id",
            "tenant",
            "archive_no",
            "inventory_mode",
            "virtual_inventory_sku",
            "status",
            "formal_product",
            "formal_spu_code",
            "formal_sku_id", "formal_sku_code", "trial_product_id", "trial_spu_code", "trial_sku_id", "trial_sku_code",
            "platform_code", "platform_name", "store_code", "store_name", "store_country_code",
            "development_spu_code", "season_code",
            "created_by_id",
            "updated_by_id",
            "trial_confirmed_by_id",
            "trial_confirmed_at",
            "formalized_by_id",
            "formalized_at",
            "created_at",
            "updated_at",
            "events",
        )
        extra_kwargs = {
            "product_name": {"required": False},
            "category": {"required": False, "allow_blank": True},
            "platform": {"required": False, "allow_null": True},
            "site": {"required": False, "allow_null": True},
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
            ProductCategory.objects.filter(
                tenant_id=tenant_id,
                is_active=True,
                level=ProductCategory.Level.L3,
            )
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
        self.fields["platform_id"].queryset = self.fields["platform_master"].queryset
        self.fields["store_id"].queryset = self.fields["store_master"].queryset

    def validate_project(self, value):
        request = self.context.get("request")
        if request is not None and value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Project must belong to the current tenant.")
        return value

    def validate_category_node(self, value):
        if value is None:
            return value
        request = self.context.get("request")
        if request is not None and value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("Category does not belong to current tenant.")
        if not value.is_active:
            raise serializers.ValidationError("An active product category is required.")
        if value.level != ProductCategory.Level.L3:
            raise serializers.ValidationError("Development products must use an active L3 leaf category.")
        try:
            category_path(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        if self.instance is not None and "project" in attrs and attrs["project"].pk != self.instance.project_id:
            raise serializers.ValidationError({"project": "The development project cannot change."})
        if self.instance is not None and self.instance.status != DevelopmentProductArchive.Status.TRIAL:
            mutable = {
                "product_name",
                "category",
                "category_node",
                "platform",
                "site",
                "platform_master",
                "platform_id",
                "store_master",
                "store_id",
                "virtual_inventory_qty",
                "test_notes",
            }
            attempted = mutable.intersection(self.initial_data)
            if attempted:
                raise serializers.ValidationError(
                    {field: "Only a virtual trial archive can be edited." for field in attempted}
                )
        if self.instance is not None and self.instance.trial_product_id:
            attempted_codes = {"development_spu_code", "season_code"}.intersection(self.initial_data)
            if attempted_codes:
                raise serializers.ValidationError({field: "Development coding is immutable after trial generation." for field in attempted_codes})

        project = attrs.get("project")
        if project is None and self.instance is not None:
            project = self.instance.project
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
            if supplied_site and str(supplied_site).strip().casefold() not in {"internal", str(store.country_code).strip().casefold()}:
                raise serializers.ValidationError({"site": "Site must match the selected store country."})
            attrs["site"] = str(store.country_code).strip().upper()
        if platform is not None:
            supplied_platform = attrs.get("platform", getattr(self.instance, "platform", ""))
            if supplied_platform and str(supplied_platform).strip().casefold() not in {"internal", str(platform.code).strip().casefold()}:
                raise serializers.ValidationError({"platform": "Platform snapshot must match the selected platform."})
            attrs["platform"] = str(platform.code).strip()

        category = attrs.get("category_node")
        if category is None and project is not None:
            # Explicit archive selection wins; otherwise carry the project
            # category, then the linked research requirement's category.
            category = getattr(project, "category_node", None)
            if category is None and project.requirement_id:
                category = getattr(project.requirement, "category_node", None)
            if category is not None:
                attrs["category_node"] = category
        if category is None:
            raise serializers.ValidationError({"category_node": "An active L3 product category is required."})
        self.validate_category_node(category)
        # Keep the legacy text column as the canonical category-name snapshot.
        attrs["category"] = category.name
        return attrs

    def get_category_path(self, obj):
        category = getattr(obj, "category_node", None)
        if category is None:
            return ""
        parts = []
        current = category
        while current is not None:
            parts.append(f"L{current.level} {current.code} {current.name}")
            current = current.parent
        return " / ".join(reversed(parts))

    def get_virtual_inventory(self, obj):
        return {
            "mode": obj.inventory_mode,
            "sku": obj.virtual_inventory_sku,
            "quantity": obj.virtual_inventory_qty,
            "platform": obj.platform,
            "site": obj.site,
        }


class DevelopmentProductArchiveConfirmationSerializer(serializers.Serializer):
    test_result = serializers.ChoiceField(
        choices=DevelopmentProductArchive.TestResult.choices,
        required=False,
        default=DevelopmentProductArchive.TestResult.PASS,
    )
    test_notes = serializers.CharField(required=False, allow_blank=True, max_length=10000)


class CompetitorReportSelectionSerializer(serializers.Serializer):
    """Only operator decisions are accepted when creating a report link."""

    relation_type = serializers.ChoiceField(
        choices=DevelopmentRequirementCompetitorLink.RelationType.choices,
        required=False,
        default=DevelopmentRequirementCompetitorLink.RelationType.REFERENCE,
    )
    is_primary = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    selected_strengths = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    selected_pain_points = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    selected_recommendations = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    evidence_ids = serializers.ListField(
        child=serializers.CharField(max_length=160), required=False, default=list, max_length=100
    )
    operator_conclusion = serializers.CharField(
        required=False, allow_blank=True, max_length=10000, default=""
    )
    excluded_items = serializers.ListField(
        child=serializers.JSONField(), required=False, default=list
    )

    def validate_excluded_items(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("No more than 100 excluded items may be submitted.")
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each excluded item must be an object.")
            if not str(item.get("reason", "")).strip():
                raise serializers.ValidationError("Each excluded item requires a reason.")
            if len(str(item.get("item", ""))) > 4000 or len(str(item.get("reason", ""))) > 2000:
                raise serializers.ValidationError("Excluded item content is too long.")
        return value

    def validate(self, attrs):
        for field in (
            "selected_strengths",
            "selected_pain_points",
            "selected_recommendations",
            "evidence_ids",
        ):
            # Normalize whitespace and remove accidental duplicates while
            # preserving the operator's chosen order in the audit snapshot.
            values = []
            for item in attrs.get(field, []):
                item = item.strip()
                if item and item not in values:
                    values.append(item)
            attrs[field] = values
        return attrs


class DevelopmentRequirementCompetitorLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentRequirementCompetitorLink
        fields = "__all__"
        read_only_fields = (
            "tenant",
            "requirement",
            "external_report_id",
            "task_id",
            "platform",
            "site",
            "product_id",
            "product_title",
            "report_completed_at",
            "data_updated_at",
            "decision_snapshot",
            "created_by",
            "created_at",
            "updated_at",
        )
