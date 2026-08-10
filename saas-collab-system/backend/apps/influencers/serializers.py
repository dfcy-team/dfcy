from rest_framework import serializers

from .models import Influencer, OutreachTask, SampleFulfillment, SampleItem, SkuPriceSnapshot


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

    class Meta:
        model = OutreachTask
        fields = (
            "id", "tenant_id", "task_no", "influencer", "store", "spu", "dispatcher_id",
            "owner", "status", "started_at", "finalized_at", "source", "external_id",
            "version", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "dispatcher_id", "status", "started_at", "finalized_at",
            "version", "created_at", "updated_at",
        )

    def validate_external_id(self, value):
        return value or None


class SampleItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleItem
        fields = (
            "id", "sku", "external_product_id", "site_code", "requested_sku", "product_name", "quantity",
            "unit_price", "unit_cost", "currency", "price_match_status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "unit_price", "unit_cost", "currency", "price_match_status", "created_at", "updated_at")


class SampleFulfillmentSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    items = SampleItemSerializer(many=True, required=False)

    class Meta:
        model = SampleFulfillment
        fields = (
            "id", "tenant_id", "fulfillment_no", "outreach_task", "influencer", "store",
            "owner", "status", "source", "external_id", "version", "finalized_at",
            "items", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "status", "version", "finalized_at", "created_at", "updated_at",
        )

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
            "promotion_price", "effective_price", "currency", "inbound_cost", "stock",
            "source_updated_at", "cost_updated_at", "imported_at",
        )
