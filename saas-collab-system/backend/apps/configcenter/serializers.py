from rest_framework import serializers

from .models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion


class SystemConfigDefinitionSerializer(serializers.ModelSerializer):
    default_value = serializers.SerializerMethodField()

    class Meta:
        model = SystemConfigDefinition
        fields = (
            "id", "config_key", "scope_type", "value_type", "default_value",
            "is_sensitive", "requires_approval", "description",
        )
        read_only_fields = fields

    def get_default_value(self, obj):
        return "***" if obj.is_sensitive else obj.default_value


class TenantConfigVersionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    value = serializers.SerializerMethodField()
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    approved_by_id = serializers.IntegerField(source="approved_by.id", read_only=True)
    is_sensitive = serializers.BooleanField(source="definition.is_sensitive", read_only=True)

    class Meta:
        model = TenantConfigVersion
        fields = (
            "id", "tenant_id", "config_key", "scope_key", "version", "value",
            "is_sensitive", "status", "effective_at", "created_by_id", "approved_by_id", "created_at",
        )
        read_only_fields = fields

    def get_value(self, obj):
        return "***" if obj.definition.is_sensitive else obj.value


class ConfigChangeLogSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)
    version_id = serializers.SerializerMethodField()

    class Meta:
        model = ConfigChangeLog
        fields = (
            "id", "tenant_id", "config_key", "scope_key", "from_version", "to_version",
            "version_id", "actor_id", "action", "masked_detail", "created_at",
        )
        read_only_fields = fields

    def get_version_id(self, obj):
        # Logs intentionally store immutable version numbers rather than a
        # mutable FK.  Resolve the current version id for action links while
        # retaining the append-only log contract.  The list endpoint annotates
        # this value in SQL; keep the fallback for direct serializer use.
        if hasattr(obj, "resolved_version_id"):
            return obj.resolved_version_id
        return TenantConfigVersion.objects.filter(
            config_key=obj.config_key,
            scope_key=obj.scope_key,
            version=obj.to_version,
        ).values_list("id", flat=True).first()


class ConfigVersionCreateSerializer(serializers.Serializer):
    config_key = serializers.CharField(max_length=120)
    value = serializers.JSONField()
    effective_at = serializers.DateTimeField()


class ConfigRollbackSerializer(serializers.Serializer):
    effective_at = serializers.DateTimeField(required=False)


class ConfigQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    config_key = serializers.CharField(max_length=120, required=False)
    status = serializers.ChoiceField(choices=TenantConfigVersion.Status.choices, required=False)
    scope = serializers.ChoiceField(choices=SystemConfigDefinition.ScopeType.choices, required=False)
