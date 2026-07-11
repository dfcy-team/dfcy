from rest_framework import serializers

from .models import BusinessAlert, BusinessAlertActionLog, BusinessAlertRule, InventoryAlert, InventoryAlertEvent


class InventoryAlertEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = InventoryAlertEvent
        fields = ("id", "event_type", "actor_id", "detail", "created_at")


class InventoryAlertSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    rule_code = serializers.CharField(source="rule.rule_code", read_only=True)
    rule_version = serializers.IntegerField(source="rule.version", read_only=True)
    assigned_to_id = serializers.IntegerField(source="assigned_to.id", read_only=True)
    events = InventoryAlertEventSerializer(many=True, read_only=True)

    class Meta:
        model = InventoryAlert
        fields = (
            "id", "tenant_id", "rule_code", "rule_version", "spu", "sku", "warehouse_code",
            "alert_type", "severity", "available_stock", "in_transit_stock", "average_daily_sales",
            "coverage_days", "threshold_value", "status", "assigned_to_id", "reason", "source_summary",
            "triggered_at", "silenced_until", "closed_at", "created_at", "updated_at", "events",
        )
        read_only_fields = fields


class InventoryAlertQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    status = serializers.ChoiceField(choices=InventoryAlert.Status.choices, required=False)
    alert_type = serializers.ChoiceField(choices=InventoryAlert._meta.get_field("alert_type").choices, required=False)
    severity = serializers.ChoiceField(choices=InventoryAlert._meta.get_field("severity").choices, required=False)


class InventoryAlertEvaluationSerializer(serializers.Serializer):
    rule_id = serializers.IntegerField(min_value=1)
    sku_id = serializers.IntegerField(min_value=1, required=False)
    spu_id = serializers.IntegerField(min_value=1, required=False)
    warehouse_code = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    available_stock = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0)
    in_transit_stock = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0)
    average_daily_sales = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("sku_id") and not attrs.get("spu_id"):
            raise serializers.ValidationError("sku_id or spu_id is required.")
        return attrs


class InventoryAlertAssignSerializer(serializers.Serializer):
    assigned_to_id = serializers.IntegerField(min_value=1)


class InventoryAlertSilenceSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=1, max_value=43200, required=False)


class InventoryAlertCloseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class BusinessAlertActionLogSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = BusinessAlertActionLog
        fields = ("id", "action", "actor_id", "note", "created_at")
        read_only_fields = fields


class BusinessAlertSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    rule_code = serializers.CharField(source="rule.rule_code", read_only=True)
    rule_version = serializers.IntegerField(source="rule.version", read_only=True)
    assigned_to_id = serializers.IntegerField(source="assigned_to.id", read_only=True)
    action_logs = BusinessAlertActionLogSerializer(many=True, read_only=True)

    class Meta:
        model = BusinessAlert
        fields = (
            "id", "tenant_id", "rule_code", "rule_version", "business_type", "business_id",
            "severity", "title", "detail", "metric_value", "threshold_value", "status",
            "assigned_to_id", "triggered_at", "silenced_until", "closed_at", "created_at",
            "updated_at", "action_logs",
        )
        read_only_fields = fields


class BusinessAlertEvaluationSerializer(serializers.Serializer):
    rule_id = serializers.IntegerField(min_value=1)
    business_type = serializers.CharField(max_length=80)
    business_id = serializers.CharField(max_length=120)
    metric_value = serializers.DecimalField(max_digits=20, decimal_places=4)
    title = serializers.CharField(max_length=200)
    detail = serializers.JSONField(required=False, default=dict)


class BusinessAlertQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    status = serializers.ChoiceField(choices=BusinessAlert.Status.choices, required=False)
    severity = serializers.ChoiceField(choices=BusinessAlertRule._meta.get_field("severity").choices, required=False)
    business_type = serializers.CharField(max_length=80, required=False)


class BusinessAlertAssignSerializer(serializers.Serializer):
    assigned_to_id = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class BusinessAlertSilenceSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=1, max_value=43200, required=False)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class BusinessAlertCloseSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, trim_whitespace=True)
