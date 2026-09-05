"""Product/SKU mapping service for marketplace variants.

Automatic discovery can only produce ``suggested`` records; ``mapped`` always
requires explicit manual confirmation. Conflicts keep the previous mapping and
never silently overwrite. Mapping writes never trigger order/inventory/finance
syncs.
"""

import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone as django_timezone

from apps.common.exceptions import StateConflict
from apps.listings.models import PlatformProductDetail
from apps.products.models import ProductSKU

from .models import (
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreMapping,
    product_mapping_service_write,
)


CONTROLLED_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,79}")

ALLOWED_TRANSITIONS = {
    MarketplaceProductMapping.Status.UNMAPPED: {
        MarketplaceProductMapping.Status.SUGGESTED,
        MarketplaceProductMapping.Status.INACTIVE,
    },
    MarketplaceProductMapping.Status.SUGGESTED: {
        MarketplaceProductMapping.Status.MAPPED,
        MarketplaceProductMapping.Status.CONFLICT,
        MarketplaceProductMapping.Status.INACTIVE,
    },
    MarketplaceProductMapping.Status.MAPPED: {
        MarketplaceProductMapping.Status.CONFLICT,
        MarketplaceProductMapping.Status.INACTIVE,
    },
    MarketplaceProductMapping.Status.CONFLICT: {
        MarketplaceProductMapping.Status.MAPPED,
        MarketplaceProductMapping.Status.INACTIVE,
    },
    MarketplaceProductMapping.Status.INACTIVE: set(),
}


def _validate_actor_tenant(actor, tenant_id):
    if actor.tenant_id != tenant_id:
        raise ValidationError("Product mapping actor must belong to the mapping tenant.")


def _validate_sku_tenant(sku, tenant_id):
    if sku is None:
        raise ValidationError({"sku": "Product mapping requires an internal SKU."})
    if sku.tenant_id != tenant_id:
        raise ValidationError({"sku": "Product mapping SKU must belong to the mapping tenant."})


def _transition_allowed(record, target):
    return target in ALLOWED_TRANSITIONS.get(record.status, set())


def _product_mapping_audit(tenant, config, actor, action, result, detail):
    IntegrationAuditLog.objects.create(
        tenant=tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail,
    )


def _platform_values(detail):
    return {
        str(detail.platform.platform_type or "").strip().lower(),
        str(detail.platform.code or "").strip().lower(),
    }


def _matching_platform_detail(*, tenant_id, store_mapping, platform_variant_id):
    """Find an exact platform/store/variant detail without guessing identity."""

    queryset = PlatformProductDetail.objects.filter(
        tenant_id=tenant_id,
        store_id=store_mapping.store_id,
        platform__platform_type=store_mapping.platform,
        platform_variant_id=platform_variant_id,
    ).select_related("platform", "internal_sku")
    matches = list(queryset[:2])
    if not matches:
        queryset = PlatformProductDetail.objects.filter(
            tenant_id=tenant_id,
            store_id=store_mapping.store_id,
            platform__code=store_mapping.platform,
            platform_variant_id=platform_variant_id,
        ).select_related("platform", "internal_sku")
        matches = list(queryset[:2])
    if len(matches) > 1:
        raise StateConflict("The platform variant matches multiple platform detail records.")
    return matches[0] if matches else None


def _validate_platform_detail_identity(
    *, detail, tenant_id, store_mapping, platform_product_id, platform_variant_id,
    platform_sku="", sku=None,
):
    """Validate identity before a mapping is linked; never overwrite detail data."""

    if detail is None:
        return
    errors = {}
    if detail.tenant_id != tenant_id:
        errors["platform_detail_id"] = "Platform product detail must belong to the mapping tenant."
    if str(store_mapping.platform or "").strip().lower() not in _platform_values(detail):
        errors["platform_detail_id"] = "Platform product detail platform must match the store mapping platform."
    if detail.store_id != store_mapping.store_id:
        errors["platform_detail_id"] = "Platform product detail store must match the store mapping store."
    if platform_variant_id and detail.platform_variant_id != platform_variant_id:
        errors["platform_variant_id"] = "Platform variant identity does not match the platform detail."
    if platform_product_id and detail.platform_product_id and detail.platform_product_id != platform_product_id:
        errors["platform_product_id"] = "Platform product identity does not match the platform detail."
    if platform_sku and detail.platform_sku and detail.platform_sku != platform_sku:
        errors["platform_sku"] = "Platform SKU does not match the platform detail."
    if sku is not None and detail.internal_sku_id and detail.internal_sku_id != sku.id:
        errors["sku_id"] = "The mapping SKU conflicts with the platform detail SKU."
    if errors:
        raise ValidationError(errors)


def create_product_mapping(
    *,
    tenant,
    actor,
    store_mapping,
    platform_product_id="",
    platform_variant_id="",
    platform_sku="",
    platform_detail=None,
    mapping_source=MarketplaceProductMapping.MappingSource.MANUAL,
):
    _validate_actor_tenant(actor, tenant.id)
    if store_mapping is None or store_mapping.tenant_id != tenant.id:
        raise ValidationError({"store_mapping": "Product mapping requires a tenant store mapping."})
    if store_mapping.status != MarketplaceStoreMapping.Status.ACTIVE:
        raise ValidationError({"store_mapping": "Product mappings require an active store mapping."})
    if platform_detail is not None:
        if platform_detail.tenant_id != tenant.id:
            raise ValidationError({"platform_detail_id": "Platform product detail must belong to the mapping tenant."})
        platform_product_id = str(platform_product_id or "").strip() or platform_detail.platform_product_id
        platform_variant_id = str(platform_variant_id or "").strip() or platform_detail.platform_variant_id
        platform_sku = str(platform_sku or "").strip() or platform_detail.platform_sku
        _validate_platform_detail_identity(
            detail=platform_detail,
            tenant_id=tenant.id,
            store_mapping=store_mapping,
            platform_product_id=platform_product_id,
            platform_variant_id=platform_variant_id,
            platform_sku=platform_sku,
        )
    platform_product_id = str(platform_product_id or "").strip()
    platform_variant_id = str(platform_variant_id or "").strip()
    if not platform_product_id or len(platform_product_id) > 160:
        raise ValidationError({"platform_product_id": "Platform product identifier is invalid."})
    if not platform_variant_id or len(platform_variant_id) > 160:
        raise ValidationError({"platform_variant_id": "Platform variant identifier is invalid."})
    if MarketplaceProductMapping.objects.filter(
        store_mapping=store_mapping,
        platform_variant_id=platform_variant_id,
    ).exists():
        raise StateConflict("The platform variant already has a mapping in this store.")
    mapping = MarketplaceProductMapping(
        tenant=tenant,
        platform=store_mapping.platform,
        store_mapping=store_mapping,
        platform_product_id=platform_product_id,
        platform_variant_id=platform_variant_id,
        platform_sku=str(platform_sku or "").strip()[:160],
        platform_detail=platform_detail,
        status=MarketplaceProductMapping.Status.UNMAPPED,
        mapping_source=mapping_source,
        created_by=actor,
        updated_by=actor,
        last_verified_at=django_timezone.now(),
    )
    with product_mapping_service_write():
        mapping.save()
    _product_mapping_audit(
        tenant,
        store_mapping.authorization.integration_config,
        actor,
        "product_mapping_create",
        IntegrationAuditLog.Result.SUCCESS,
        {
            "platform_variant_id": platform_variant_id,
            "store_mapping_id": store_mapping.id,
            "mapping_source": mapping.mapping_source,
        },
    )
    return mapping


def suggest_product_mapping(record, *, actor, sku, confidence):
    """Apply an automatic/manual candidate suggestion; never maps directly."""

    _validate_actor_tenant(actor, record.tenant_id)
    _validate_sku_tenant(sku, record.tenant_id)
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= 100:
        raise ValidationError({"confidence": "Confidence must be an integer between 0 and 100."})
    if record.platform_detail_id:
        _validate_platform_detail_identity(
            detail=record.platform_detail,
            tenant_id=record.tenant_id,
            store_mapping=record.store_mapping,
            platform_product_id=record.platform_product_id,
            platform_variant_id=record.platform_variant_id,
            platform_sku=record.platform_sku,
        )
        if (
            record.status in {
                MarketplaceProductMapping.Status.UNMAPPED,
                MarketplaceProductMapping.Status.SUGGESTED,
            }
            and record.platform_detail.internal_sku_id
            and record.platform_detail.internal_sku_id != sku.id
        ):
            # Keep the canonical detail SKU untouched, but retain the newly
            # suggested candidate on the controlled mapping as an explicit
            # conflict.  Confirmation can subsequently replace the canonical
            # SKU with an expected-value check; rejecting the suggestion here
            # would leave the operator with no way to resolve the conflict.
            previous_sku_id = record.sku_id
            previous_status = record.status
            record.status = MarketplaceProductMapping.Status.CONFLICT
            record.result_code = "MAPPING_CONFLICT"
            record.sku = sku
            record.product = sku.spu
            record.confidence = confidence
            record.manually_confirmed = False
            if record.mapping_source == MarketplaceProductMapping.MappingSource.MANUAL:
                record.mapping_source = MarketplaceProductMapping.MappingSource.SUGGESTED
            record.updated_by = actor
            record.last_verified_at = django_timezone.now()
            with product_mapping_service_write():
                record.save()
            _product_mapping_audit(
                record.tenant,
                record.store_mapping.authorization.integration_config,
                actor,
                "product_mapping_conflict",
                IntegrationAuditLog.Result.SUCCESS,
                {
                    "platform_variant_id": record.platform_variant_id,
                    "kept_sku_id": record.platform_detail.internal_sku_id,
                    "previous_mapping_sku_id": previous_sku_id,
                    "conflicting_sku_id": sku.id,
                    "previous_status": previous_status,
                    "result_code": record.result_code,
                },
            )
            return record
    if record.status == MarketplaceProductMapping.Status.MAPPED:
        if record.sku_id == sku.id:
            record.last_verified_at = django_timezone.now()
            record.updated_by = actor
            with product_mapping_service_write():
                record.save()
            return record
        if not _transition_allowed(record, MarketplaceProductMapping.Status.CONFLICT):
            raise StateConflict("The product mapping cannot enter conflict from its current state.")
        record.status = MarketplaceProductMapping.Status.CONFLICT
        record.result_code = "MAPPING_CONFLICT"
        record.confidence = confidence
        record.updated_by = actor
        with product_mapping_service_write():
            record.save()
        _product_mapping_audit(
            record.tenant,
            record.store_mapping.authorization.integration_config,
            actor,
            "product_mapping_conflict",
            IntegrationAuditLog.Result.SUCCESS,
            {
                "platform_variant_id": record.platform_variant_id,
                "kept_sku_id": record.sku_id,
                "conflicting_sku_id": sku.id,
                "result_code": record.result_code,
            },
        )
        return record
    if record.status not in {
        MarketplaceProductMapping.Status.UNMAPPED,
        MarketplaceProductMapping.Status.SUGGESTED,
    }:
        raise StateConflict("Only unmapped or suggested product mappings accept new suggestions.")
    record.status = MarketplaceProductMapping.Status.SUGGESTED
    record.sku = sku
    record.product = sku.spu
    record.confidence = confidence
    record.manually_confirmed = False
    if record.mapping_source == MarketplaceProductMapping.MappingSource.MANUAL:
        record.mapping_source = MarketplaceProductMapping.MappingSource.SUGGESTED
    record.updated_by = actor
    record.last_verified_at = django_timezone.now()
    with product_mapping_service_write():
        record.save()
    _product_mapping_audit(
        record.tenant,
        record.store_mapping.authorization.integration_config,
        actor,
        "product_mapping_suggest",
        IntegrationAuditLog.Result.SUCCESS,
        {"platform_variant_id": record.platform_variant_id, "sku_id": sku.id, "confidence": confidence},
    )
    return record


@transaction.atomic
def confirm_product_mapping(
    record,
    *,
    actor,
    sku=None,
    manually_confirmed=False,
    expected_internal_sku_id=None,
    replace_existing=False,
):
    """Manual confirmation; the only path to ``mapped`` status."""

    # Always lock the decision and its canonical detail so two concurrent
    # confirmations cannot assign different internal SKUs.
    record = MarketplaceProductMapping.objects.select_for_update().select_related(
        "store_mapping__authorization__integration_config",
        "store_mapping__store",
        "platform_detail__platform",
        "platform_detail__internal_sku",
        "sku",
    ).get(pk=record.pk)
    _validate_actor_tenant(actor, record.tenant_id)
    if not manually_confirmed:
        raise ValidationError({"manually_confirmed": "Mapping confirmation requires explicit manual approval."})
    if replace_existing and expected_internal_sku_id is None:
        raise ValidationError({"expected_internal_sku_id": "替换已有 SKU 必须提交确认前的内部 SKU ID。"})
    candidate = sku or record.sku
    _validate_sku_tenant(candidate, record.tenant_id)
    detail = record.platform_detail
    if detail is None:
        detail = _matching_platform_detail(
            tenant_id=record.tenant_id,
            store_mapping=record.store_mapping,
            platform_variant_id=record.platform_variant_id,
        )
    before_internal_sku_id = detail.internal_sku_id if detail is not None else None
    if detail is not None:
        detail = PlatformProductDetail.objects.select_for_update().select_related(
            "platform", "internal_sku"
        ).get(pk=detail.pk)
        before_internal_sku_id = detail.internal_sku_id
        if expected_internal_sku_id is not None and before_internal_sku_id != expected_internal_sku_id:
            raise StateConflict("平台商品明细已被其他操作更新，请刷新后重新确认。")
        _validate_platform_detail_identity(
            detail=detail,
            tenant_id=record.tenant_id,
            store_mapping=record.store_mapping,
            platform_product_id=record.platform_product_id,
            platform_variant_id=record.platform_variant_id,
            platform_sku=record.platform_sku,
        )
        if detail.internal_sku_id and detail.internal_sku_id != candidate.id and not replace_existing:
            raise StateConflict(
                "The platform detail already has a different internal SKU; submit replace_existing with the expected SKU to replace it."
            )
    elif expected_internal_sku_id is not None:
        raise StateConflict("平台商品明细不存在，无法校验待替换的内部 SKU。")
    if record.status == MarketplaceProductMapping.Status.MAPPED and record.sku_id == candidate.id:
        if detail is not None and detail.internal_sku_id != candidate.id:
            detail.internal_sku = candidate
            detail.save(update_fields=["internal_sku", "updated_at"])
        if detail is not None and record.platform_detail_id is None:
            record.platform_detail = detail
            with product_mapping_service_write():
                record.save(update_fields=["platform_detail", "updated_at"])
        return record
    if not _transition_allowed(record, MarketplaceProductMapping.Status.MAPPED):
        raise StateConflict("Only suggested or conflicted product mappings can be confirmed.")
    existing = MarketplaceProductMapping.objects.select_for_update().filter(
        store_mapping=record.store_mapping,
        sku=candidate,
        status=MarketplaceProductMapping.Status.MAPPED,
    ).exclude(pk=record.pk)
    if existing.exists():
        raise StateConflict("The internal SKU is already mapped to another platform variant in this store.")
    previous_sku_id = record.sku_id
    record.status = MarketplaceProductMapping.Status.MAPPED
    record.sku = candidate
    record.product = candidate.spu
    record.manually_confirmed = True
    record.result_code = ""
    record.updated_by = actor
    record.last_verified_at = django_timezone.now()
    if detail is not None:
        # Update the canonical fact row before saving the decision record so
        # model validation sees the same SKU on both sides.  The surrounding
        # transaction rolls both writes back on any error.
        if detail.internal_sku_id != candidate.id:
            detail.internal_sku = candidate
            detail.save(update_fields=["internal_sku", "updated_at"])
        record.platform_detail = detail
    with product_mapping_service_write():
        record.save()
    _product_mapping_audit(
        record.tenant,
        record.store_mapping.authorization.integration_config,
        actor,
        "product_mapping_confirm",
        IntegrationAuditLog.Result.SUCCESS,
        {
            "platform_variant_id": record.platform_variant_id,
            "sku_id": candidate.id,
            "manually_confirmed": True,
            "before_internal_sku_id": before_internal_sku_id,
            "after_internal_sku_id": detail.internal_sku_id if detail is not None else None,
            "previous_mapping_sku_id": previous_sku_id,
            "expected_internal_sku_id": expected_internal_sku_id,
            "replaced_existing": bool(replace_existing and before_internal_sku_id not in {None, candidate.id}),
        },
    )
    return record


def deactivate_product_mapping(record, *, actor, result_code="MANUAL_DEACTIVATED"):
    _validate_actor_tenant(actor, record.tenant_id)
    if record.status == MarketplaceProductMapping.Status.INACTIVE:
        return record
    if not _transition_allowed(record, MarketplaceProductMapping.Status.INACTIVE):
        raise StateConflict("The product mapping cannot be deactivated from its current state.")
    if not CONTROLLED_CODE_PATTERN.fullmatch(str(result_code or "")):
        raise ValidationError({"result_code": "Deactivation requires a controlled uppercase error code."})
    record.status = MarketplaceProductMapping.Status.INACTIVE
    record.result_code = result_code
    record.updated_by = actor
    with product_mapping_service_write():
        record.save()
    _product_mapping_audit(
        record.tenant,
        record.store_mapping.authorization.integration_config,
        actor,
        "product_mapping_deactivate",
        IntegrationAuditLog.Result.SUCCESS,
        {"platform_variant_id": record.platform_variant_id, "result_code": result_code},
    )
    return record


def deactivate_mappings_for_sku(sku, *, actor, result_code="SKU_INVALIDATED"):
    """Controlled SKU invalidation: related mappings go inactive, never deleted."""

    deactivated = []
    for mapping in MarketplaceProductMapping.objects.filter(sku=sku).exclude(
        status=MarketplaceProductMapping.Status.INACTIVE
    ):
        deactivated.append(deactivate_product_mapping(mapping, actor=actor, result_code=result_code))
    return deactivated


def sku_candidates_for_mapping(record):
    """Candidate SKUs are always restricted to the mapping tenant."""

    return ProductSKU.objects.filter(tenant_id=record.tenant_id).order_by("sku_code")
