from contextlib import contextmanager
from contextvars import ContextVar
import hashlib

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant
from django.conf import settings


_authorization_service_write = ContextVar("authorization_service_write", default=False)
_oauth_service_write = ContextVar("oauth_service_write", default=False)


@contextmanager
def authorization_service_write():
    token = _authorization_service_write.set(True)
    try:
        yield
    finally:
        _authorization_service_write.reset(token)


@contextmanager
def oauth_service_write():
    token = _oauth_service_write.set(True)
    try:
        yield
    finally:
        _oauth_service_write.reset(token)


class PlatformChoices(models.TextChoices):
    BIGSELLER = "bigseller", "BigSeller"
    SHOPEE = "shopee", "Shopee"
    TIKTOK = "tiktok", "TikTok"
    MOCK = "mock", "Mock"
    OTHER = "other", "Other"


class PlatformIntegrationConfigQuerySet(models.QuerySet):
    reference_fields = {
        "credential_id",
        "token_id",
        "credential_mask",
        "credential_reference_version",
        "credential_key_version",
        "credential_fingerprint",
    }

    def update(self, **kwargs):
        if not _authorization_service_write.get() and self.reference_fields.intersection(kwargs):
            raise ValidationError("Credential references can only be changed by the rotation service.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        if not _authorization_service_write.get() and any(
            obj.credential_id
            or obj.token_id
            or obj.credential_mask
            or obj.credential_key_version
            or obj.credential_fingerprint
            or obj.credential_reference_version != 1
            for obj in objs
        ):
            raise ValidationError("Credential references can only be created by the rotation service.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if not _authorization_service_write.get() and self.reference_fields.intersection(fields):
            raise ValidationError("Credential references can only be changed by the rotation service.")
        return super().bulk_update(objs, fields, **kwargs)


class PlatformIntegrationConfig(models.Model):
    class Environment(models.TextChoices):
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        PENDING_REVIEW = "pending_review", "Pending review"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="platform_integration_configs")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    account_alias = models.CharField(max_length=120)
    environment = models.CharField(max_length=20, choices=Environment.choices, default=Environment.MOCK)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DISABLED)
    credential_id = models.CharField(max_length=160, blank=True)
    token_id = models.CharField(max_length=160, blank=True)
    credential_mask = models.JSONField(default=dict, blank=True)
    credential_reference_version = models.PositiveIntegerField(default=1)
    credential_key_version = models.CharField(max_length=40, blank=True)
    credential_fingerprint = models.CharField(max_length=64, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_platform_integration_configs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PlatformIntegrationConfigQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "platform", "account_alias"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "platform", "account_alias", "environment"],
                name="uniq_platform_integration_per_tenant",
            ),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.platform}:{self.account_alias}"

    def save(self, *args, **kwargs):
        if not _authorization_service_write.get():
            fields = PlatformIntegrationConfigQuerySet.reference_fields
            if self.pk:
                current = type(self).objects.only(*fields).get(pk=self.pk)
                if any(getattr(current, field) != getattr(self, field) for field in fields):
                    raise ValidationError("Credential references can only be changed by the rotation service.")
            elif (
                self.credential_id
                or self.token_id
                or self.credential_mask
                or self.credential_key_version
                or self.credential_fingerprint
                or self.credential_reference_version != 1
            ):
                raise ValidationError("Credential references can only be created by the rotation service.")
        return super().save(*args, **kwargs)


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Integration audit records are append-only.")

    def delete(self):
        raise ValidationError("Integration audit records cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Integration audit records are append-only.")


class IntegrationAuditLog(models.Model):
    class Result(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="integration_audit_logs")
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    store_authorization = models.ForeignKey(
        "MarketplaceStoreAuthorization",
        on_delete=models.PROTECT,
        related_name="audit_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=80)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="integration_audit_logs",
    )
    result = models.CharField(max_length=20, choices=Result.choices)
    masked_detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.integration_config_id}:{self.action}:{self.result}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Integration audit records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Integration audit records cannot be deleted.")


class MarketplaceStoreAuthorizationQuerySet(models.QuerySet):
    protected_fields = {
        "tenant",
        "tenant_id",
        "integration_config",
        "integration_config_id",
        "store",
        "store_id",
        "platform",
        "region",
        "platform_store_id",
        "platform_identity_key",
        "merchant_subject_id",
        "shop_cipher",
        "status",
        "credential_id",
        "token_id",
        "credential_mask",
        "credential_reference_version",
        "authorized_at",
        "expires_at",
        "refreshed_at",
        "revoked_at",
        "last_error_code",
        "scopes",
        "created_by",
        "created_by_id",
        "updated_by",
        "updated_by_id",
    }

    protected_attnames = {
        "tenant_id",
        "integration_config_id",
        "store_id",
        "platform",
        "region",
        "platform_store_id",
        "platform_identity_key",
        "merchant_subject_id",
        "shop_cipher",
        "status",
        "credential_id",
        "token_id",
        "credential_mask",
        "credential_reference_version",
        "authorized_at",
        "expires_at",
        "refreshed_at",
        "revoked_at",
        "last_error_code",
        "scopes",
        "created_by_id",
        "updated_by_id",
    }

    def update(self, **kwargs):
        if not _authorization_service_write.get() and self.protected_fields.intersection(kwargs):
            raise ValidationError("Authorization state can only be changed by the service layer.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if not _authorization_service_write.get():
            raise ValidationError("Store authorizations must be created by the service layer.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if not _authorization_service_write.get() and self.protected_fields.intersection(fields):
            raise ValidationError("Authorization state can only be changed by the service layer.")
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("Store authorization records cannot be deleted.")


def marketplace_identity_key(platform, region, platform_store_id):
    normalized = f"{str(platform).lower()}:{str(region).upper()}:{str(platform_store_id).strip()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


class MarketplaceStoreAuthorization(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        REVOKING = "revoking", "Revoking"
        RECONCILE_REQUIRED = "reconcile_required", "Reconcile required"
        REVOKED = "revoked", "Revoked"
        ERROR = "error", "Error"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_store_authorizations")
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.PROTECT,
        related_name="store_authorizations",
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster",
        on_delete=models.PROTECT,
        related_name="marketplace_authorizations",
    )
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    region = models.CharField(max_length=8)
    platform_store_id = models.CharField(max_length=120)
    platform_identity_key = models.CharField(max_length=64)
    merchant_subject_id = models.CharField(max_length=160)
    shop_cipher = models.CharField(max_length=255, blank=True)
    credential_id = models.CharField(max_length=160)
    token_id = models.CharField(max_length=160)
    credential_mask = models.JSONField(default=dict, blank=True)
    credential_reference_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scopes = models.JSONField(default=list, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_marketplace_store_authorizations",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_marketplace_store_authorizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MarketplaceStoreAuthorizationQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "platform", "store_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "platform_identity_key"],
                name="uniq_market_store_global_identity",
            ),
            models.UniqueConstraint(
                fields=["tenant", "platform", "store"],
                name="uniq_market_store_tenant_link",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_market_auth_tenant_status"),
            models.Index(fields=["tenant", "store"], name="idx_market_auth_tenant_store"),
        ]

    def clean(self):
        errors = {}
        if self.platform not in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
            errors["platform"] = "Store authorization only supports Shopee or TikTok Shop."
        if self.store_id:
            if self.tenant_id != self.store.tenant_id:
                errors["store"] = "Store tenant must match authorization tenant."
            if self.platform != self.store.platform.platform_type:
                errors["platform"] = "Authorization platform must match the store platform."
        if self.integration_config_id:
            if self.tenant_id != self.integration_config.tenant_id:
                errors["integration_config"] = "Integration config tenant must match authorization tenant."
            if self.platform != self.integration_config.platform:
                errors["integration_config"] = "Integration config platform must match authorization platform."
        if self.platform == PlatformChoices.TIKTOK and not self.shop_cipher:
            errors["shop_cipher"] = "TikTok Shop authorization requires shop_cipher."
        if self.platform_identity_key != marketplace_identity_key(self.platform, self.region, self.platform_store_id):
            errors["platform_identity_key"] = "Platform identity key does not match the platform store identity."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not _authorization_service_write.get():
            if not self.pk:
                raise ValidationError("Store authorizations must be created by the service layer.")
            if self.pk:
                fields = MarketplaceStoreAuthorizationQuerySet.protected_attnames
                current = type(self).objects.only(*fields).get(pk=self.pk)
                if any(getattr(current, field) != getattr(self, field) for field in fields):
                    raise ValidationError("Authorization state can only be changed by the service layer.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Store authorization records cannot be deleted.")

    def __str__(self):
        return f"{self.tenant_id}:{self.platform}:{self.store_id}:{self.status}"


class MarketplaceOAuthAttemptQuerySet(models.QuerySet):
    protected_fields = {
        "tenant", "tenant_id", "internal_user", "internal_user_id", "session_hash",
        "platform", "integration_config", "integration_config_id", "store", "store_id",
        "region", "redirect_target_code", "state_hash", "idempotency_key_hash",
        "request_fingerprint_hash", "status", "expires_at", "consumed_at", "request_id",
        "operation_id_hash", "last_error_code", "contract_version", "updated_at",
    }

    def update(self, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth attempts can only be changed by the OAuth service layer.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth attempts must be created by the OAuth service layer.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth attempts can only be changed by the OAuth service layer.")
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("OAuth attempts cannot be deleted.")


class MarketplaceOAuthAttempt(models.Model):
    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        CALLBACK_RECEIVED = "callback_received", "Callback received"
        EXCHANGED = "exchanged", "Exchanged"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_oauth_attempts")
    internal_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_oauth_attempts",
    )
    session_hash = models.CharField(max_length=64)
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.PROTECT,
        related_name="oauth_attempts",
    )
    store = models.ForeignKey(
        "masterdata.StoreMaster",
        on_delete=models.PROTECT,
        related_name="marketplace_oauth_attempts",
    )
    region = models.CharField(max_length=8)
    redirect_target_code = models.CharField(max_length=40)
    state_hash = models.CharField(max_length=64, unique=True)
    idempotency_key_hash = models.CharField(max_length=64)
    request_fingerprint_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.INITIATED)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    request_id = models.UUIDField()
    operation_id_hash = models.CharField(max_length=64)
    last_error_code = models.CharField(max_length=80, blank=True)
    contract_version = models.CharField(max_length=40, default="a2-synthetic-v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MarketplaceOAuthAttemptQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key_hash"],
                name="uniq_oauth_attempt_tenant_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_oauth_tenant_status"),
            models.Index(fields=["expires_at"], name="idx_oauth_expires"),
        ]

    def save(self, *args, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth attempts can only be written by the OAuth service layer.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("OAuth attempts cannot be deleted.")


class MarketplaceOAuthActionQuerySet(models.QuerySet):
    immutable_binding_fields = {
        "tenant", "tenant_id", "internal_user", "internal_user_id", "action",
        "object_type", "object_id", "session_hash", "idempotency_key_hash",
        "request_fingerprint_hash", "operation_id_hash", "attempt", "attempt_id",
        "authorization", "authorization_id",
    }

    def update(self, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth actions can only be changed by the OAuth service layer.")
        if self.immutable_binding_fields.intersection(kwargs):
            raise ValidationError("OAuth action bindings cannot be changed by QuerySet update.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth actions must be created by the OAuth service layer.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth actions can only be changed by the OAuth service layer.")
        if self.immutable_binding_fields.intersection(fields):
            raise ValidationError("OAuth action bindings cannot be changed by bulk update.")
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("OAuth actions cannot be deleted.")


class MarketplaceOAuthAction(models.Model):
    class Action(models.TextChoices):
        INITIATE = "initiate", "Initiate"
        REFRESH = "refresh", "Refresh"
        REVOKE = "revoke", "Revoke"
        RETRY = "retry", "Retry"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        RECONCILE_REQUIRED = "reconcile_required", "Reconcile required"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_oauth_actions")
    internal_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="marketplace_oauth_actions",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=80, blank=True)
    session_hash = models.CharField(max_length=64)
    idempotency_key_hash = models.CharField(max_length=64)
    request_fingerprint_hash = models.CharField(max_length=64)
    operation_id_hash = models.CharField(max_length=64)
    attempt = models.ForeignKey(
        MarketplaceOAuthAttempt,
        on_delete=models.PROTECT,
        related_name="actions",
        null=True,
        blank=True,
    )
    authorization = models.ForeignKey(
        MarketplaceStoreAuthorization,
        on_delete=models.PROTECT,
        related_name="oauth_actions",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    response_data = models.JSONField(default=dict, blank=True)
    response_status = models.PositiveSmallIntegerField(default=200)
    error_code = models.CharField(max_length=80, blank=True)
    execution_owner = models.CharField(max_length=64, blank=True)
    execution_fence = models.PositiveBigIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    contract_version = models.CharField(max_length=40, default="a2-synthetic-v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MarketplaceOAuthActionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "internal_user", "action", "idempotency_key_hash"],
                name="uniq_oauth_action_scope_key",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_oauth_action_status"),
            models.Index(fields=["operation_id_hash"], name="idx_oauth_action_operation"),
        ]

    def save(self, *args, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth actions can only be written by the OAuth service layer.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.internal_user_id and self.tenant_id and self.internal_user.tenant_id != self.tenant_id:
            errors["internal_user"] = "OAuth action user must belong to the action tenant."
        if self.attempt_id and self.tenant_id and self.attempt.tenant_id != self.tenant_id:
            errors["attempt"] = "OAuth action attempt must belong to the action tenant."
        if self.attempt_id and self.internal_user_id and self.attempt.internal_user_id != self.internal_user_id:
            errors["attempt"] = "OAuth action attempt must belong to the action user."
        if self.authorization_id and self.tenant_id and self.authorization.tenant_id != self.tenant_id:
            errors["authorization"] = "OAuth action authorization must belong to the action tenant."
        if self.attempt_id and self.authorization_id:
            if self.attempt.store_id != self.authorization.store_id:
                errors["authorization"] = "OAuth action attempt and authorization must bind one store."
            if self.attempt.integration_config_id != self.authorization.integration_config_id:
                errors["authorization"] = "OAuth action attempt and authorization must bind one config."
            if self.attempt.platform != self.authorization.platform:
                errors["authorization"] = "OAuth action attempt and authorization must bind one platform."
        if self.object_type == "oauth_attempt" and (
            not self.attempt_id or self.object_id != str(self.attempt_id)
        ):
            errors["object_id"] = "OAuth attempt actions must bind their attempt ID."
        if self.object_type == "store_authorization" and (
            not self.authorization_id or self.object_id != str(self.authorization_id)
        ):
            errors["object_id"] = "Store authorization actions must bind their authorization ID."
        if self.object_type == "store_target" and self.attempt_id and self.object_id != str(self.attempt.store_id):
            errors["object_id"] = "OAuth initiation target must bind the attempt store."
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError("OAuth actions cannot be deleted.")


class MarketplaceOAuthOperationQuerySet(models.QuerySet):
    immutable_binding_fields = {
        "tenant", "tenant_id", "action", "operation_id_hash", "attempt", "attempt_id",
        "authorization", "authorization_id",
    }

    def update(self, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth operations can only be changed by the OAuth service layer.")
        if self.immutable_binding_fields.intersection(kwargs):
            raise ValidationError("OAuth operation bindings cannot be changed by QuerySet update.")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth operations must be created by the OAuth service layer.")
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth operations can only be changed by the OAuth service layer.")
        if self.immutable_binding_fields.intersection(fields):
            raise ValidationError("OAuth operation bindings cannot be changed by bulk update.")
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("OAuth operations cannot be deleted.")


class MarketplaceOAuthOperation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        COMPENSATION_REQUIRED = "compensation_required", "Compensation required"
        RECONCILE_REQUIRED = "reconcile_required", "Reconcile required"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_oauth_operations")
    action = models.CharField(max_length=20)
    operation_id_hash = models.CharField(max_length=64, unique=True)
    attempt = models.ForeignKey(
        MarketplaceOAuthAttempt,
        on_delete=models.PROTECT,
        related_name="operations",
        null=True,
        blank=True,
    )
    authorization = models.ForeignKey(
        MarketplaceStoreAuthorization,
        on_delete=models.PROTECT,
        related_name="oauth_operations",
        null=True,
        blank=True,
    )
    phase = models.CharField(max_length=40, default="created")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    execution_owner = models.CharField(max_length=64, blank=True)
    execution_fence = models.PositiveBigIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    contract_version = models.CharField(max_length=40, default="a2-synthetic-v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MarketplaceOAuthOperationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_oauth_op_status"),
            models.Index(fields=["authorization", "status"], name="idx_oauth_op_auth_status"),
        ]

    def save(self, *args, **kwargs):
        if not _oauth_service_write.get():
            raise ValidationError("OAuth operations can only be written by the OAuth service layer.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def clean(self):
        errors = {}
        if self.attempt_id and self.tenant_id and self.attempt.tenant_id != self.tenant_id:
            errors["attempt"] = "OAuth operation attempt must belong to the operation tenant."
        if self.authorization_id and self.tenant_id and self.authorization.tenant_id != self.tenant_id:
            errors["authorization"] = "OAuth operation authorization must belong to the operation tenant."
        if self.attempt_id and self.authorization_id:
            if self.attempt.store_id != self.authorization.store_id:
                errors["authorization"] = "OAuth operation attempt and authorization must bind one store."
            if self.attempt.integration_config_id != self.authorization.integration_config_id:
                errors["authorization"] = "OAuth operation attempt and authorization must bind one config."
            if self.attempt.platform != self.authorization.platform:
                errors["authorization"] = "OAuth operation attempt and authorization must bind one platform."
        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError("OAuth operations cannot be deleted.")


class MarketplaceOAuthResourceLease(models.Model):
    """Durable per-resource fencing state for OAuth mutations."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="marketplace_oauth_resource_leases")
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=80)
    execution_owner = models.CharField(max_length=64, blank=True)
    fence_token = models.PositiveBigIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "object_type", "object_id"],
                name="uniq_oauth_resource_lease",
            ),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.object_type}:{self.object_id}"


class SyncJob(models.Model):
    class ResourceType(models.TextChoices):
        SALES_ORDER = "sales_order", "Sales order"
        INVENTORY = "inventory", "Inventory"
        SETTLEMENT_BILL = "settlement_bill", "Settlement bill"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        MOCK_RECORD = "mock_record", "Mock record"

    class ScheduleType(models.TextChoices):
        MANUAL = "manual", "Manual"
        INTERVAL = "interval", "Interval"
        CRON = "cron", "Cron"

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        DISABLED = "disabled", "Disabled"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_jobs")
    integration_config = models.ForeignKey(
        PlatformIntegrationConfig,
        on_delete=models.PROTECT,
        related_name="sync_jobs",
    )
    resource_type = models.CharField(max_length=40, choices=ResourceType.choices)
    schedule_type = models.CharField(max_length=20, choices=ScheduleType.choices, default=ScheduleType.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    is_enabled = models.BooleanField(default=True)
    max_retry_count = models.PositiveIntegerField(default=3)
    backoff_base_seconds = models.PositiveIntegerField(default=1)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    lock_token = models.CharField(max_length=80, blank=True)
    lock_acquired_at = models.DateTimeField(null=True, blank=True)
    lock_expires_at = models.DateTimeField(null=True, blank=True)
    lock_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "resource_type", "id"]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_sync_job_tenant_status"),
            models.Index(fields=["tenant", "resource_type"], name="idx_sync_job_tenant_resource"),
        ]

    def __str__(self):
        return f"{self.integration_config_id}:{self.resource_type}:{self.status}"


class SyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_runs")
    sync_job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name="runs")
    run_id = models.CharField(max_length=80)
    idempotency_key = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    fetched_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)
    masked_error_message = models.TextField(blank=True)
    masked_log = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "sync_job", "idempotency_key"],
                name="uniq_sync_run_job_idempotency",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"], name="idx_sync_run_tenant_status"),
            models.Index(fields=["run_id"], name="idx_sync_run_run_id"),
        ]

    def __str__(self):
        return f"{self.run_id}:{self.status}"


class SyncCursor(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="sync_cursors")
    sync_job = models.ForeignKey(SyncJob, on_delete=models.CASCADE, related_name="cursors")
    cursor_key = models.CharField(max_length=80)
    cursor_value = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "sync_job_id", "cursor_key"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sync_job", "cursor_key"], name="uniq_sync_cursor_key"),
        ]

    def __str__(self):
        return f"{self.sync_job_id}:{self.cursor_key}"


class WebhookEvent(models.Model):
    class SignatureStatus(models.TextChoices):
        MOCK_VALID = "mock_valid", "Mock valid"
        INVALID = "invalid", "Invalid"
        NOT_CONFIGURED = "not_configured", "Not configured"

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed"
        DUPLICATE = "duplicate", "Duplicate"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="webhook_events")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    signature_status = models.CharField(max_length=30, choices=SignatureStatus.choices)
    processing_status = models.CharField(
        max_length=30,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    payload_hash = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "platform", "event_id"], name="uniq_webhook_event_per_tenant"),
        ]

    def __str__(self):
        return f"{self.platform}:{self.event_id}:{self.processing_status}"


class APIIntegrationConfig(models.Model):
    """Legacy integration metadata retained for migration compatibility only."""

    is_legacy = True
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISABLED = "disabled", "Disabled"

    class Environment(models.TextChoices):
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        PRODUCTION = "production", "Production"

    class CredentialStatus(models.TextChoices):
        PLACEHOLDER = "placeholder", "Placeholder"
        ACTIVE = "active", "Active"
        ROTATION_REQUIRED = "rotation_required", "Rotation required"
        REVOKED = "revoked", "Revoked"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_integration_configs")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    shop_code = models.CharField(max_length=80)
    api_base_url = models.URLField()
    environment = models.CharField(max_length=20, choices=Environment.choices, default=Environment.MOCK)
    auth_scheme = models.CharField(max_length=40, default="hmac_sha256")
    credential_ref = models.CharField(max_length=160, blank=True)
    credential_key_version = models.CharField(max_length=40, blank=True)
    credential_status = models.CharField(
        max_length=30,
        choices=CredentialStatus.choices,
        default=CredentialStatus.PLACEHOLDER,
    )
    credential_expires_at = models.DateTimeField(null=True, blank=True)
    last_rotated_at = models.DateTimeField(null=True, blank=True)
    least_privilege_scope = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Legacy API integration config"
        verbose_name_plural = "Legacy API integration configs"
        ordering = ["tenant_id", "platform", "shop_code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "platform", "shop_code"], name="uniq_api_config_shop_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.platform}:{self.shop_code}"


class APISyncTask(models.Model):
    class SyncType(models.TextChoices):
        SALES_ORDER = "sales_order", "Sales order"
        INVENTORY = "inventory", "Inventory"
        INBOUND = "inbound", "Inbound"
        SHIPMENT = "shipment", "Shipment"
        SETTLEMENT_BILL = "settlement_bill", "Settlement bill"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL_SUCCESS = "partial_success", "Partial success"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_sync_tasks")
    platform = models.CharField(max_length=30, choices=PlatformChoices.choices)
    sync_type = models.CharField(max_length=40, choices=SyncType.choices)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retry_count = models.PositiveIntegerField(default=3)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "platform", "sync_type"]
        indexes = [
            models.Index(fields=["tenant", "platform", "sync_type"], name="idx_api_task_tenant_type"),
            models.Index(fields=["status", "next_sync_at"], name="idx_api_task_schedule"),
        ]

    def __str__(self):
        return f"{self.platform}:{self.sync_type}:{self.status}"


class APISyncLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_sync_logs")
    task = models.ForeignKey(APISyncTask, on_delete=models.CASCADE, related_name="logs")
    status = models.CharField(max_length=30, choices=APISyncTask.Status.choices)
    request_url = models.URLField(blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.task_id}:{self.status}"


class APIDataQualityCheck(models.Model):
    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        WARNING = "warning", "Warning"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_data_quality_checks")
    sync_log = models.ForeignKey(APISyncLog, on_delete=models.CASCADE, related_name="quality_checks")
    check_type = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices)
    message = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sync_log_id", "check_type"]

    def __str__(self):
        return f"{self.check_type}:{self.status}"
