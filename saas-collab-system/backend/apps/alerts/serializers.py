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
    assigned_to_name = serializers.SerializerMethodField()
    sku_code = serializers.SerializerMethodField()
    legacy_sku_code = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()
    events = InventoryAlertEventSerializer(many=True, read_only=True)

    class Meta:
        model = InventoryAlert
        fields = (
            "id", "tenant_id", "rule_code", "rule_version", "spu", "sku", "warehouse_code",
            "alert_type", "severity", "available_stock", "in_transit_stock", "average_daily_sales",
            "coverage_days", "threshold_value", "status", "assigned_to_id", "reason", "source_summary",
            "assigned_to_name", "action_plan", "due_date", "resolution", "version", "sku_code",
            "legacy_sku_code", "product_name", "triggered_at", "silenced_until", "closed_at",
            "created_at", "updated_at", "events",
        )
        read_only_fields = fields

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to_id:
            return ""
        return obj.assigned_to.full_name or obj.assigned_to.username

    def get_sku_code(self, obj):
        return obj.sku.sku_code if obj.sku_id else ""

    def get_legacy_sku_code(self, obj):
        return obj.sku.legacy_sku_code if obj.sku_id else ""

    def get_product_name(self, obj):
        return (obj.sku.product_name if obj.sku_id else "") or (obj.spu.product_name if obj.spu_id else "")


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
    expected_version = serializers.IntegerField(min_value=1, required=False)


class InventoryAlertSilenceSerializer(serializers.Serializer):
    minutes = serializers.IntegerField(min_value=1, max_value=43200, required=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class InventoryAlertCloseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class InventoryAlertFollowUpSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    assigned_to_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    action_plan = serializers.CharField(max_length=10000, required=False, allow_blank=True, trim_whitespace=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=((InventoryAlert.Status.OPEN, "Open"), (InventoryAlert.Status.ASSIGNED, "Assigned"),
                 (InventoryAlert.Status.IN_PROGRESS, "In progress")),
        required=False,
    )


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
