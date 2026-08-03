from rest_framework import serializers

from .models import IntegrationAuditLog, MarketplaceStoreAuthorization, PlatformIntegrationConfig, SyncJob, SyncRun


RAW_CREDENTIAL_FIELDS = {
    "credentials",
    "credential_ciphertext",
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "secret",
    "token",
    "cookie",
    "session",
    "password",
}
CONTROLLED_REFERENCE_FIELDS = {
    "credential_id",
    "token_id",
    "credential_mask",
    "credential_reference_version",
}


class RejectRawCredentialFieldsMixin:
    def to_internal_value(self, data):
        rejected = sorted(RAW_CREDENTIAL_FIELDS & set(data)) if hasattr(data, "keys") else []
        if rejected:
            raise serializers.ValidationError(
                {field: "Raw credential material is not accepted; use an external credential reference." for field in rejected}
            )
        controlled = sorted(CONTROLLED_REFERENCE_FIELDS & set(data)) if hasattr(data, "keys") else []
        if controlled:
            raise serializers.ValidationError(
                {field: "Credential references can only be changed by the controlled service." for field in controlled}
            )
        return super().to_internal_value(data)


class PlatformIntegrationConfigSerializer(RejectRawCredentialFieldsMixin, serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = PlatformIntegrationConfig
        fields = (
            "id",
            "tenant_id",
            "platform",
            "account_alias",
            "environment",
            "status",
            "credential_key_version",
            "credential_fingerprint",
            "credential_mask",
            "credential_reference_version",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "credential_fingerprint",
            "credential_mask",
            "credential_key_version",
            "credential_reference_version",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        environment = attrs.get("environment", getattr(self.instance, "environment", None))
        status = attrs.get("status", getattr(self.instance, "status", PlatformIntegrationConfig.Status.DISABLED))
        if (
            environment == PlatformIntegrationConfig.Environment.PRODUCTION
            and status == PlatformIntegrationConfig.Status.ACTIVE
        ):
            raise serializers.ValidationError(
                {"status": "Production configs can only be disabled or pending review in phase 2."}
        )
        return attrs


class RotateCredentialsSerializer(RejectRawCredentialFieldsMixin, serializers.Serializer):
    def validate(self, attrs):
        raise serializers.ValidationError(
            "Legacy encrypted credential rotation is retired. Marketplace reference rotation remains pending."
        )


class MarketplaceStoreAuthorizationSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_id = serializers.IntegerField(read_only=True)
    integration_config_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)
    updated_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketplaceStoreAuthorization
        fields = (
            "id",
            "tenant_id",
            "platform",
            "store_id",
            "integration_config_id",
            "region",
            "platform_store_id",
            "merchant_subject_id",
            "shop_cipher",
            "credential_mask",
            "credential_reference_version",
            "status",
            "scopes",
            "authorized_at",
            "expires_at",
            "refresh_due_at",
            "revoked_at",
            "masked_error_code",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class IntegrationAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationAuditLog
        fields = ("id", "action", "actor_id", "result", "masked_detail", "created_at")
        read_only_fields = fields


class SyncJobSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    integration_config_id = serializers.IntegerField()

    class Meta:
        model = SyncJob
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
            "resource_type",
            "schedule_type",
            "status",
            "is_enabled",
            "max_retry_count",
            "backoff_base_seconds",
            "last_run_at",
            "next_run_at",
            "lock_expires_at",
            "lock_heartbeat_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "status",
            "last_run_at",
            "next_run_at",
            "lock_expires_at",
            "lock_heartbeat_at",
            "created_at",
            "updated_at",
        )

    def validate_integration_config_id(self, value):
        request = self.context["request"]
        if not PlatformIntegrationConfig.objects.filter(id=value, tenant=request.user.tenant).exists():
            raise serializers.ValidationError("Integration config does not belong to current tenant.")
        return value

    def validate_max_retry_count(self, value):
        if value > 5:
            raise serializers.ValidationError("max_retry_count cannot exceed 5 in phase 2.")
        return value

    def validate_backoff_base_seconds(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("backoff_base_seconds must be between 1 and 5 in phase 2.")
        return value


class SyncRunSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    sync_job_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SyncRun
        fields = (
            "id",
            "tenant_id",
            "sync_job_id",
            "run_id",
            "idempotency_key",
            "status",
            "started_at",
            "finished_at",
            "fetched_count",
            "created_count",
            "updated_count",
            "skipped_count",
            "failed_count",
            "retry_count",
            "error_code",
            "masked_error_message",
            "masked_log",
        )
        read_only_fields = fields
