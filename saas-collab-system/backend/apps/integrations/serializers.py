from rest_framework import serializers

from .credential_service import encrypt_credentials, mask_credentials
from .models import IntegrationAuditLog, PlatformIntegrationConfig


class PlatformIntegrationConfigSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    credential_mask = serializers.SerializerMethodField()
    credentials = serializers.DictField(write_only=True, required=False)

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
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
            "credentials",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "credential_fingerprint",
            "credential_mask",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def get_credential_mask(self, obj):
        return {"fingerprint": obj.credential_fingerprint, "key_version": obj.credential_key_version}

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
        key_version = validated_data.get("credential_key_version") or "test-v1"
        if credentials:
            ciphertext, fingerprint = encrypt_credentials(credentials, key_version=key_version)
            validated_data["credential_ciphertext"] = ciphertext
            validated_data["credential_fingerprint"] = fingerprint
            validated_data["credential_key_version"] = key_version
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("credentials", None)
        return super().update(instance, validated_data)


class RotateCredentialsSerializer(serializers.Serializer):
    credentials = serializers.DictField()
    credential_key_version = serializers.CharField(max_length=40)


class IntegrationAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationAuditLog
        fields = ("id", "action", "actor_id", "result", "masked_detail", "created_at")
        read_only_fields = fields
