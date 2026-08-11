from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.masterdata.models import StoreMaster

from .models import (
    Influencer,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
)


class InfluencerSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    is_blacklisted = serializers.SerializerMethodField()

    class Meta:
        model = Influencer
        fields = (
            "id", "tenant_id", "code", "name", "platform", "category",
            "follower_count", "cooperation_status", "status", "is_blacklisted",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "cooperation_status", "status", "created_at", "updated_at", "is_blacklisted",
        )
    def validate_code(self, value):
        request = self.context["request"]
        queryset = Influencer.objects.filter(tenant=request.user.tenant, code=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Code must be unique within the current tenant.")
        return value

    def get_is_blacklisted(self, obj):
        return obj.restrictions.filter(is_blacklisted=True).exists()


class OutreachTaskSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    dispatcher_id = serializers.IntegerField(read_only=True)
    linked_count = serializers.SerializerMethodField()

    def get_linked_count(self, obj):
        annotated = getattr(obj, "active_linked_count", None)
        return annotated if annotated is not None else obj.linked_count

    class Meta:
        model = OutreachTask
        fields = (
            "id", "tenant_id", "task_no", "task_name", "influencer", "store", "spu",
            "external_product_id", "sku_prefix", "target_count", "linked_count", "dispatcher_id",
            "owner", "dispatch_time", "outreach_at", "status", "started_at", "finalized_at",
            "is_deleted", "deleted_at", "source", "external_id", "version", "notes",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "dispatcher_id", "linked_count", "status", "dispatch_time", "outreach_at",
            "started_at", "finalized_at", "is_deleted", "deleted_at", "version",
            "created_at", "updated_at",
        )

        extra_kwargs = {
            "influencer": {"required": False, "allow_null": True},
            "task_name": {"required": False, "allow_blank": True},
            "external_product_id": {"required": False, "allow_blank": True},
            "sku_prefix": {"required": False, "allow_blank": True},
            "target_count": {"required": False, "min_value": 0},
            "notes": {"required": False, "allow_blank": True},
        }

    def validate_external_id(self, value):
        return value or None


class OutreachTargetSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = OutreachTarget
        fields = (
            "id", "tenant_id", "task", "influencer", "first_linked_at", "outreach_result",
            "version", "notes", "is_deleted", "deleted_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "task", "first_linked_at", "version", "is_deleted", "deleted_at",
            "created_at", "updated_at",
        )

        extra_kwargs = {
            "influencer": {"required": True},
            "notes": {"required": False, "allow_blank": True},
            "outreach_result": {"required": False},
        }


class SampleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleItem
        fields = (
            "id", "sku", "external_product_id", "site_code", "requested_sku", "product_name", "quantity",
            "unit_price", "currency", "price_match_status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "unit_price", "currency", "price_match_status", "created_at", "updated_at")

    def validate_requested_sku(self, value):
        return value.strip() or None if value is not None else None


class SampleFulfillmentSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    outreach_task = serializers.PrimaryKeyRelatedField(queryset=OutreachTask.objects.all())
    outreach_target = serializers.PrimaryKeyRelatedField(
        queryset=OutreachTarget.objects.all(), required=False, allow_null=True
    )
    influencer = serializers.PrimaryKeyRelatedField(
        queryset=Influencer.objects.all(), required=False, allow_null=True
    )
    store = serializers.PrimaryKeyRelatedField(
        queryset=StoreMaster.objects.all(),
        required=False,
        allow_null=True,
    )
    owner = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        required=False,
        allow_null=True,
    )
    items = SampleItemSerializer(many=True, required=False)

    class Meta:
        model = SampleFulfillment
        fields = (
            "id", "tenant_id", "fulfillment_no", "outreach_task", "outreach_target", "influencer",
            "store", "owner", "product_name_snapshot", "external_product_id", "sample_order_no",
            "sample_sent_at", "shipped_at", "status", "source", "external_id", "version",
            "notes", "finalized_at", "items", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "product_name_snapshot", "sample_sent_at", "shipped_at", "status",
            "version", "finalized_at", "created_at", "updated_at",
        )

        extra_kwargs = {
            "fulfillment_no": {"required": True},
            "external_product_id": {"required": False, "allow_blank": True},
            "sample_order_no": {"required": False, "allow_blank": True},
            "source": {"required": False},
            "external_id": {"required": False, "allow_null": True, "allow_blank": True},
            "notes": {"required": False, "allow_blank": True},
        }

    def validate_external_id(self, value):
        return value or None


class SkuPriceSnapshotSerializer(serializers.ModelSerializer):
    store_id = serializers.IntegerField(source="listing.store_id", read_only=True)
    store_name = serializers.CharField(source="listing.store.name", read_only=True)
    site_code = serializers.CharField(source="listing.site_code", read_only=True)
    product_id = serializers.CharField(source="listing.external_product_id", read_only=True)
    product_name = serializers.CharField(source="listing.product_name", read_only=True)
    parent_sku = serializers.CharField(source="listing.parent_sku", read_only=True)

    class Meta:
        model = SkuPriceSnapshot
        fields = (
            "id", "store_id", "store_name", "site_code", "product_id", "product_name",
            "parent_sku", "external_sku", "variant_id", "variant_name", "original_price",
            "promotion_price", "effective_price", "currency", "source_updated_at", "imported_at",
        )
