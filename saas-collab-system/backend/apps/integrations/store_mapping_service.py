"""Store mapping service: binds authorized platform stores to internal stores.

Platform identity always derives from the ``MarketplaceStoreAuthorization``
record; request payloads never supply platform store identifiers. All writes
run inside ``store_mapping_service_write`` and are audited with masked values.
"""

from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone

from apps.common.exceptions import StateConflict

from .models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    store_mapping_service_write,
)


ALLOWED_MAPPING_PLATFORMS = {"shopee", "tiktok"}


def _validate_actor_tenant(actor, tenant_id):
    if actor.tenant_id != tenant_id:
        raise ValidationError("Store mapping actor must belong to the mapping tenant.")


def _validate_currency(currency):
    currency = str(currency or "").strip().upper()
    if currency and (len(currency) != 3 or not currency.isalpha()):
        raise ValidationError({"currency": "Currency must be an uppercase ISO 4217 code."})
    return currency


def _mapping_audit(tenant, config, actor, action, result, detail):
    IntegrationAuditLog.objects.create(
        tenant=tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail,
    )


def create_store_mapping(
    *,
    tenant,
    actor,
    store,
    authorization,
    mapping_source=MarketplaceStoreMapping.MappingSource.MANUAL,
    store_timezone="",
    currency="",
):
    _validate_actor_tenant(actor, tenant.id)
    if store is None:
        raise ValidationError({"store": "Store mapping requires an internal store."})
    if store.tenant_id != tenant.id:
        raise ValidationError({"store": "Store mapping store must belong to the current tenant."})
    if authorization is None or authorization.tenant_id != tenant.id:
        raise ValidationError({"authorization": "Store mapping requires a tenant authorization."})
    if authorization.platform not in ALLOWED_MAPPING_PLATFORMS:
        raise ValidationError({"authorization": "Store mappings only support Shopee or TikTok Shop."})
    if store.platform.platform_type != authorization.platform:
        raise ValidationError({"store": "Internal store platform must match the authorization platform."})
    if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
        raise ValidationError(
            {"authorization": "Active store mappings require an active authorization."}
        )
    currency = _validate_currency(currency)
    if MarketplaceStoreMapping.objects.filter(
        tenant=tenant,
        platform=authorization.platform,
        platform_store_id=authorization.platform_store_id,
    ).exists():
        raise StateConflict("The platform store already has a mapping in this tenant.")
    mapping = MarketplaceStoreMapping(
        tenant=tenant,
        platform=authorization.platform,
        store=store,
        authorization=authorization,
        platform_store_id=authorization.platform_store_id,
        platform_identity_key=authorization.platform_identity_key,
        platform_subject_id=authorization.merchant_subject_id,
        region=authorization.region,
        timezone=str(store_timezone or "").strip()[:64],
        currency=currency,
        status=MarketplaceStoreMapping.Status.ACTIVE,
        mapping_source=mapping_source,
        mapped_by=actor,
        last_verified_at=django_timezone.now(),
    )
    with store_mapping_service_write():
        mapping.save()
    _mapping_audit(
        tenant,
        authorization.integration_config,
        actor,
        "store_mapping_create",
        IntegrationAuditLog.Result.SUCCESS,
        {
            "platform": mapping.platform,
            "platform_store_id": mapping.platform_store_id,
            "store_id": store.id,
            "status": mapping.status,
            "mapping_source": mapping.mapping_source,
        },
    )
    return mapping


def update_store_mapping(record, *, actor, status=None, store_timezone=None, currency=None):
    _validate_actor_tenant(actor, record.tenant_id)
    previous = {"status": record.status, "timezone": record.timezone, "currency": record.currency}
    changed = {}
    if status is not None:
        if status not in MarketplaceStoreMapping.Status.values:
            raise ValidationError({"status": "Unsupported store mapping status."})
        if status != record.status:
            if status == MarketplaceStoreMapping.Status.ACTIVE:
                if record.authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
                    raise ValidationError(
                        {"status": "Reactivating a mapping requires an active authorization."}
                    )
            record.status = status
            changed["status"] = status
    if store_timezone is not None:
        normalized_timezone = str(store_timezone).strip()[:64]
        if normalized_timezone != record.timezone:
            record.timezone = normalized_timezone
            changed["timezone"] = normalized_timezone
    if currency is not None:
        normalized_currency = _validate_currency(currency)
        if normalized_currency != record.currency:
            record.currency = normalized_currency
            changed["currency"] = normalized_currency
    if not changed:
        return record
    record.last_verified_at = django_timezone.now()
    with store_mapping_service_write():
        record.save()
    _mapping_audit(
        record.tenant,
        record.authorization.integration_config,
        actor,
        "store_mapping_update",
        IntegrationAuditLog.Result.SUCCESS,
        {"previous": previous, "changed": changed, "platform_store_id": record.platform_store_id},
    )
    return record
