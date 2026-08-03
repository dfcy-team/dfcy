import hashlib
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import BusinessRuleViolation, DataScopeDenied, StateConflict, get_scoped_object_or_404
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import store_authorization_values_allowed

from .models import IntegrationAuditLog, MarketplaceStoreAuthorization, PlatformChoices


LOGICAL_READ_SCOPES = {"shop.read", "order.read", "product.read", "inventory.read"}


def _require_action(actor, permission_code, *, platform, store_id):
    if (
        not actor
        or not actor.is_authenticated
        or actor.user_type != CustomUser.UserType.INTERNAL
        or not check_user_permission(actor, permission_code)
    ):
        raise DataScopeDenied("The exact marketplace action permission is required.")
    if not store_authorization_values_allowed(
        actor,
        permission_code,
        platform=platform,
        store_id=store_id,
    ):
        raise DataScopeDenied(
            "Marketplace store is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )


def _validate_synthetic_identifier(value, prefix, field_name):
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
        raise BusinessRuleViolation(f"{field_name} must use a synthetic {prefix} reference in this release.")


def _identity_key(platform, region, platform_store_id):
    canonical = f"{platform}:{region.upper()}:{platform_store_id.strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit(authorization, actor, action, result=IntegrationAuditLog.Result.SUCCESS, detail=None):
    return IntegrationAuditLog.objects.create(
        tenant=authorization.tenant,
        integration_config=authorization.integration_config,
        store_authorization=authorization,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail or {},
    )


def _save(authorization, actor, update_fields=None):
    authorization.updated_by = actor
    authorization._service_write = True
    fields = list(update_fields or [])
    if fields and "updated_by" not in fields:
        fields.append("updated_by")
    if fields and "updated_at" not in fields:
        fields.append("updated_at")
    try:
        authorization.save(update_fields=fields or None)
    finally:
        authorization._service_write = False
    return authorization


@transaction.atomic
def create_pending_store_authorization(
    *,
    actor,
    integration_config,
    store,
    platform_store_id,
    merchant_subject_id,
    shop_cipher="",
    scopes=None,
):
    _require_action(
        actor,
        "integrations.store.authorize",
        platform=integration_config.platform,
        store_id=store.id,
    )
    if actor.tenant_id != integration_config.tenant_id or actor.tenant_id != store.tenant_id:
        raise DataScopeDenied("Marketplace authorization must stay within the actor tenant.")
    if integration_config.environment != integration_config.Environment.MOCK:
        raise BusinessRuleViolation("Only mock marketplace authorization records are allowed in this release.")
    if integration_config.platform not in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        raise BusinessRuleViolation("Only Shopee and TikTok Shop authorization records are supported.")
    _validate_synthetic_identifier(platform_store_id, "mock-store-", "platform_store_id")
    _validate_synthetic_identifier(merchant_subject_id, "mock-merchant-", "merchant_subject_id")
    if integration_config.platform == PlatformChoices.TIKTOK:
        _validate_synthetic_identifier(shop_cipher, "mock-shop-cipher-", "shop_cipher")
    granted_scopes = scopes or []
    if set(granted_scopes) - LOGICAL_READ_SCOPES:
        raise BusinessRuleViolation("Only the frozen logical read scopes are accepted in this release.")

    authorization = MarketplaceStoreAuthorization(
        tenant=actor.tenant,
        platform=integration_config.platform,
        store=store,
        integration_config=integration_config,
        region=store.country_code.upper(),
        platform_store_id=platform_store_id,
        platform_identity_key=_identity_key(
            integration_config.platform,
            store.country_code,
            platform_store_id,
        ),
        merchant_subject_id=merchant_subject_id,
        shop_cipher=shop_cipher,
        scopes=granted_scopes,
        status=MarketplaceStoreAuthorization.Status.PENDING,
        created_by=actor,
        updated_by=actor,
    )
    try:
        _save(authorization, actor)
    except IntegrityError as exc:
        raise StateConflict("The platform store is already bound.") from exc
    except DjangoValidationError as exc:
        if set(getattr(exc, "error_dict", {})) == {"__all__"}:
            raise StateConflict("The platform store is already bound.") from exc
        raise BusinessRuleViolation("Marketplace store binding validation failed.") from exc
    _audit(
        authorization,
        actor,
        "store_authorization.created_mock",
        detail={"platform": authorization.platform, "store_id": authorization.store_id, "status": authorization.status},
    )
    return authorization


def _locked_authorization(actor, authorization_id, permission_code):
    queryset = (
        MarketplaceStoreAuthorization.objects.select_for_update()
        .select_related("tenant", "store", "store__platform", "integration_config")
        .filter(tenant_id=actor.tenant_id)
    )
    authorization = get_scoped_object_or_404(queryset, pk=authorization_id)
    _require_action(
        actor,
        permission_code,
        platform=authorization.platform,
        store_id=authorization.store_id,
    )
    return authorization


@transaction.atomic
def activate_mock_store_authorization(
    *, actor, authorization_id, credential_id, token_id, expires_at=None, refresh_due_at=None
):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.authorize")
    if authorization.status != MarketplaceStoreAuthorization.Status.PENDING:
        raise StateConflict("Only a pending mock authorization can become active.")
    _validate_synthetic_identifier(credential_id, "mock-credential-", "credential_id")
    _validate_synthetic_identifier(token_id, "mock-token-", "token_id")
    authorization.credential_id = credential_id
    authorization.token_id = token_id
    authorization.credential_mask = {"credential": "mock-credential-***", "token": "mock-token-***"}
    authorization.credential_reference_version += 1
    authorization.status = MarketplaceStoreAuthorization.Status.ACTIVE
    authorization.authorized_at = timezone.now()
    authorization.expires_at = expires_at
    authorization.refresh_due_at = refresh_due_at
    authorization.revoked_at = None
    authorization.masked_error_code = ""
    _save(
        authorization,
        actor,
        [
            "credential_id",
            "token_id",
            "credential_mask",
            "credential_reference_version",
            "status",
            "authorized_at",
            "expires_at",
            "refresh_due_at",
            "revoked_at",
            "masked_error_code",
        ],
    )
    _audit(
        authorization,
        actor,
        "store_authorization.activated_mock",
        detail={"reference_version": authorization.credential_reference_version, "status": authorization.status},
    )
    return authorization


@transaction.atomic
def rotate_mock_credential_references(*, actor, authorization_id, credential_id, token_id):
    authorization = _locked_authorization(actor, authorization_id, "integrations.credential.rotate")
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    }:
        raise StateConflict("Credential references cannot be rotated in the current state.")
    _validate_synthetic_identifier(credential_id, "mock-credential-", "credential_id")
    _validate_synthetic_identifier(token_id, "mock-token-", "token_id")
    authorization.credential_id = credential_id
    authorization.token_id = token_id
    authorization.credential_mask = {"credential": "mock-credential-***", "token": "mock-token-***"}
    authorization.credential_reference_version += 1
    _save(
        authorization,
        actor,
        ["credential_id", "token_id", "credential_mask", "credential_reference_version"],
    )
    _audit(
        authorization,
        actor,
        "store_authorization.credential_reference_rotated_mock",
        detail={"reference_version": authorization.credential_reference_version},
    )
    return authorization


@transaction.atomic
def revoke_mock_store_authorization(*, actor, authorization_id):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.revoke")
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.PENDING,
        MarketplaceStoreAuthorization.Status.ACTIVE,
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    }:
        raise StateConflict("The mock authorization cannot be revoked in the current state.")
    authorization.status = MarketplaceStoreAuthorization.Status.REVOKED
    authorization.revoked_at = timezone.now()
    _save(authorization, actor, ["status", "revoked_at"])
    _audit(authorization, actor, "store_authorization.revoked_mock", detail={"status": authorization.status})
    return authorization


@transaction.atomic
def retry_mock_store_authorization(*, actor, authorization_id):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.retry")
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.EXPIRED,
        MarketplaceStoreAuthorization.Status.ERROR,
    }:
        raise StateConflict("Only expired or error mock authorizations can be retried.")
    authorization.status = MarketplaceStoreAuthorization.Status.PENDING
    authorization.masked_error_code = ""
    _save(authorization, actor, ["status", "masked_error_code"])
    _audit(authorization, actor, "store_authorization.retry_requested_mock", detail={"status": authorization.status})
    return authorization


@transaction.atomic
def expire_mock_store_authorization(*, actor, authorization_id):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.authorize")
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        raise StateConflict("Only an active mock authorization can expire.")
    authorization.status = MarketplaceStoreAuthorization.Status.EXPIRED
    _save(authorization, actor, ["status"])
    _audit(authorization, actor, "store_authorization.expired_mock", detail={"status": authorization.status})
    return authorization


@transaction.atomic
def record_mock_sync_request(*, actor, authorization_id):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.sync")
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        raise StateConflict("Only an active mock authorization can request synchronization.")
    _audit(authorization, actor, "store_authorization.sync_requested_mock", detail={"execution": False})
    return authorization


@transaction.atomic
def record_mock_authorization_error(*, actor, authorization_id, error_code):
    authorization = _locked_authorization(actor, authorization_id, "integrations.store.sync")
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.PENDING,
        MarketplaceStoreAuthorization.Status.ACTIVE,
    }:
        raise StateConflict("The mock authorization cannot enter error state from its current state.")
    if not isinstance(error_code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", error_code):
        raise BusinessRuleViolation("A bounded masked error code is required.")
    authorization.status = MarketplaceStoreAuthorization.Status.ERROR
    authorization.masked_error_code = error_code
    _save(authorization, actor, ["status", "masked_error_code"])
    _audit(
        authorization,
        actor,
        "store_authorization.error_recorded_mock",
        result=IntegrationAuditLog.Result.FAILED,
        detail={"error_code": error_code, "status": authorization.status},
    )
    return authorization
