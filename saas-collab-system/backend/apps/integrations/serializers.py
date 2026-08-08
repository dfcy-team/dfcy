from rest_framework import serializers

from .credential_service import store_credentials
from .custody import CredentialCustodyError
from .models import IntegrationAuditLog, PlatformIntegrationConfig, SyncJob, SyncRun


class PlatformIntegrationConfigSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    credential_mask = serializers.SerializerMethodField()
    credentials = serializers.DictField(write_only=True, required=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True, write_only=True)

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
            "credential_id",
            "token_id",
            "credential_version",
            "credential_status",
            "credential_expires_at",
            "credential_operation_id_hash",
            "credential_revoked_at",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
            "credentials",
            "expires_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "credential_fingerprint",
            "credential_mask",
            "credential_id",
            "token_id",
            "credential_version",
            "credential_status",
            "credential_expires_at",
            "credential_operation_id_hash",
            "credential_revoked_at",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def get_credential_mask(self, obj):
        # Keep the response metadata-only.  ``credential_fingerprint`` and
        # ``credential_key_version`` are retained solely for old records; new
        # custody writes use opaque IDs, a fixed mask, version and expiry.
        return {
            "credential_id": obj.credential_id,
            "token_id": obj.token_id,
            "mask": obj.credential_mask or "***",
            "version": obj.credential_version,
            "status": obj.credential_status,
            "expires_at": obj.credential_expires_at,
            "fingerprint": obj.credential_fingerprint,
            "key_version": obj.credential_key_version,
        }

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

    def create(self, validated_data):
        credentials = validated_data.pop("credentials", {})
        expires_at = validated_data.pop("expires_at", None)
        if not credentials:
            return super().create(validated_data)

        # Secrets enter the independent custody boundary before the business
        # model is written.  Only the safe reference metadata is copied into
        # ``validated_data``; legacy ciphertext/fingerprint columns are never
        # populated by this path.
        request = self.context.get("request")
        idempotency_key = request.headers.get("Idempotency-Key") if request else None
        operation_id = request.headers.get("X-Request-ID") if request else None
        try:
            reference = store_credentials(
                credentials,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
        except CredentialCustodyError as exc:
            # Custody exceptions intentionally contain no input values.  Map
            # them to a normal API validation response rather than leaking a
            # storage traceback to callers.
            raise serializers.ValidationError("Credential custody operation failed.") from exc
        reference_data = reference.to_dict()
        validated_data.update(
            {
                "credential_id": reference_data["credential_id"],
                "token_id": reference_data["token_id"],
                "credential_mask": reference_data["mask"],
                "credential_version": reference_data["version"],
                "credential_status": reference_data["status"],
                "credential_expires_at": reference_data["expires_at"],
                "credential_operation_id_hash": reference_data["operation_id_hash"] or "",
            }
        )
        # ``credential_expires_at`` is a model DateTimeField, while the local
        # store returns ISO metadata.  Let DRF/Django handle a datetime-like
        # value only when one was supplied; the normal store path has no
        # expiry and therefore remains ``None``.
        if reference_data["expires_at"]:
            from datetime import datetime

            validated_data["credential_expires_at"] = datetime.fromisoformat(
                reference_data["expires_at"].replace("Z", "+00:00")
            )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("credentials", None)
        return super().update(instance, validated_data)


class RotateCredentialsSerializer(serializers.Serializer):
    credentials = serializers.DictField()
    credential_key_version = serializers.CharField(max_length=40)
    expires_at = serializers.DateTimeField(required=False, allow_null=True, write_only=True)


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
