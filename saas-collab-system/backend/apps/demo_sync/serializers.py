from rest_framework import serializers

from apps.accounts.models import CustomUser
from .contracts import MAX_WINDOW_DAYS, RESOURCES
from .models import SyncEnvironment, SnapshotBatch


class EnvironmentSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(required=False, min_value=1)
    owner_name = serializers.CharField(source="owner.username", read_only=True)
    resources = serializers.ListField(child=serializers.ChoiceField(choices=list(RESOURCES)), allow_empty=False)
    store_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=20, required=True)
    warehouse_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=20, required=True)

    class Meta:
        model = SyncEnvironment
        fields = ["id", "name", "owner_id", "owner_name", "resources", "store_ids", "warehouse_ids", "active", "created_at"]
        read_only_fields = ["id", "active", "created_at"]

    def validate(self, data):
        user = self.context["request"].user
        owner_id = data.get("owner_id", user.pk)
        if not CustomUser.objects.filter(pk=owner_id, tenant_id=user.tenant_id, is_active=True, user_type="internal").exists():
            raise serializers.ValidationError({"owner_id": "请选择本租户有效内部用户。"})
        data["owner_id"] = owner_id
        for key in ("resources", "store_ids", "warehouse_ids"):
            data[key] = list(dict.fromkeys(data[key]))
        if {"sales_orders", "sales_order_items"}.intersection(data["resources"]) and not data["store_ids"]:
            raise serializers.ValidationError({"store_ids": "同步销售数据必须指定店铺范围。"})
        if "inventory_snapshots" in data["resources"] and not data["warehouse_ids"]:
            raise serializers.ValidationError({"warehouse_ids": "同步库存必须指定仓库范围。"})
        return data


class BatchInputSerializer(serializers.Serializer):
    environment_id = serializers.IntegerField(min_value=1)
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, data):
        days = (data["date_to"] - data["date_from"]).days
        if days < 0 or days >= MAX_WINDOW_DAYS:
            raise serializers.ValidationError("日期窗口必须为 1–31 天。")
        return data


class BatchSerializer(serializers.ModelSerializer):
    environment_id = serializers.IntegerField(read_only=True)
    environment_name = serializers.CharField(source="environment.name", read_only=True)

    class Meta:
        model = SnapshotBatch
        fields = ["id", "environment_id", "environment_name", "status", "resources", "date_from", "date_to", "summary", "error_code", "created_at", "started_at", "heartbeat_at", "finished_at"]
