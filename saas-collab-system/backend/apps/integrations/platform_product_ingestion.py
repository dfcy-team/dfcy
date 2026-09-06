"""Canonical platform-product ingestion for store API synchronization.

The adapter layer is responsible for fetching and normalizing a platform
response.  This module owns the tenant/store-scoped write boundary: it
upserts one :class:`PlatformProductDetail` per platform/store/variant,
resolves the supplied new and legacy SKU codes together, and exposes the
existing controlled mapping UI for anything that cannot be resolved safely.

The service is deliberately read/prepare-only from a platform perspective;
it never calls an external API and never publishes or writes a listing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import StateConflict
from apps.listings.models import PlatformProductDetail
from apps.listings.platform_product_details import (
    SKUResolutionError,
    build_sku_resolution_caches,
    _clean_sku,
    _parse_datetime,
    _resolve_site,
    _resolve_sku,
    resolve_platform_sku,
    _text,
)
from apps.masterdata.models import CountrySiteMaster, PlatformMaster, StoreMaster

from .models import (
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreMapping,
    product_mapping_service_write,
)
from .product_mapping_service import (
    _product_mapping_audit,
    auto_associate_product_mapping,
    create_product_mapping,
)


INGESTION_SOURCE = "api"
DETAIL_FIELDS = (
    "site",
    "platform_product_id",
    "platform_sku",
    "source_old_sku_code",
    "internal_sku",
    "title",
    "variant",
    "category_l1",
    "category_l2",
    "category_l3",
    "sku_prefix",
    "shop_abbr",
    "sales_status",
    "owner",
    "leader",
    "platform_created_at",
    "platform_updated_at",
    "source",
)


def _platform_for_value(tenant, value):
    value = _text(value).lower()
    if not value:
        raise ValidationError({"platform": "平台不能为空。"})
    matches = list(
        PlatformMaster.objects.filter(tenant=tenant)
        .filter(code__iexact=value)
        .order_by("id")[:2]
    )
    if not matches:
        matches = list(
            PlatformMaster.objects.filter(tenant=tenant)
            .filter(platform_type__iexact=value)
            .order_by("id")[:2]
        )
    if not matches:
        matches = list(
            PlatformMaster.objects.filter(tenant=tenant)
            .filter(name__iexact=value)
            .order_by("id")[:2]
        )
    if len(matches) != 1:
        raise ValidationError({"platform": "平台不存在或无法唯一匹配当前租户。"})
    return matches[0]


def _platform_for(sync_job, record):
    """Use the authorized store's platform as the production authority."""

    tenant = sync_job.tenant
    config = sync_job.integration_config
    if config.tenant_id != tenant.id:
        raise ValidationError({"integration_config": "同步配置不属于当前租户。"})
    authorization = getattr(sync_job, "store_authorization", None)
    if authorization is not None:
        if (
            authorization.tenant_id != tenant.id
            or authorization.integration_config_id != config.id
            or authorization.status != authorization.Status.ACTIVE
            or authorization.store_id is None
        ):
            raise ValidationError({"store_authorization": "生产商品同步必须使用当前租户的有效店铺授权。"})
        store_platform = authorization.store.platform
        configured = _text(config.platform).lower()
        platform_keys = {
            _text(store_platform.code).lower(),
            _text(store_platform.name).lower(),
            _text(store_platform.platform_type).lower(),
        }
        if configured not in platform_keys or _text(authorization.platform).lower() not in platform_keys:
            raise ValidationError({"platform": "同步配置、店铺授权和店铺档案的平台不一致。"})
        supplied = _text(record.get("platform")).lower()
        if supplied and supplied not in platform_keys:
            raise ValidationError({"platform": "平台商品记录的平台与店铺授权不一致。"})
        return store_platform
    if config.environment in {"pilot", "production"}:
        raise ValidationError({"store_authorization": "生产商品同步缺少有效店铺授权。"})
    return _platform_for_value(tenant, config.platform)


def _store_for(sync_job, platform, record):
    """Resolve the store from the authorized sync subject or explicit ID."""

    tenant = sync_job.tenant
    authorization = getattr(sync_job, "store_authorization", None)
    if authorization is not None:
        if authorization.tenant_id != tenant.id:
            raise ValidationError({"store": "店铺授权不属于当前租户。"})
        if authorization.store_id is None:
            raise ValidationError({"store": "店铺授权未绑定店铺档案。"})
        store = authorization.store
        if store.platform_id != platform.id:
            raise ValidationError({"store": "店铺授权的平台与商品平台不一致。"})
        explicit = _text(record.get("store_id") or record.get("store_code"))
        if explicit and explicit != str(store.id) and explicit.casefold() not in {
            _text(store.code).casefold(),
            _text(store.name).casefold(),
        }:
            raise ValidationError({"store": "平台商品店铺与同步任务授权店铺不一致。"})
        return store

    value = _text(record.get("store_id") or record.get("store_code") or record.get("store"))
    if not value:
        raise ValidationError({"store": "商品同步必须绑定店铺授权或提供店铺标识。"})
    queryset = StoreMaster.objects.filter(tenant=tenant, platform=platform)
    matches = list(queryset.filter(code__iexact=value).order_by("id")[:2])
    if not matches:
        try:
            matches = list(queryset.filter(pk=int(value)).order_by("id")[:2])
        except (TypeError, ValueError):
            matches = []
    if not matches:
        matches = list(queryset.filter(name__iexact=value).order_by("id")[:2])
    if len(matches) != 1:
        raise ValidationError({"store": "店铺不存在或无法唯一匹配当前租户。"})
    return matches[0]


def _as_row(record):
    """Adapt the stable normalized adapter shape to the import resolver."""

    if not isinstance(record, Mapping):
        raise ValidationError("平台商品记录必须是对象。")
    old_code = record.get("source_old_sku_code")
    if old_code in (None, ""):
        old_code = record.get("old_sku_code", record.get("legacy_sku_code"))
    new_code = record.get("new_sku_code")
    if new_code in (None, ""):
        new_code = record.get("internal_sku_code")
    return {
        "new_sku_code": _clean_sku(new_code),
        "source_old_sku_code": _clean_sku(old_code),
    }


def _resolve_ingestion_sku(tenant, record, new_skus=None, legacy_skus=None):
    row = _as_row(record)
    try:
        if row["new_sku_code"] or row["source_old_sku_code"]:
            return _resolve_sku(tenant, row, new_skus, legacy_skus), None
        # A generic platform SKU is not assumed to be legacy.  Resolve it
        # against the union of the new and legacy namespaces and only accept a
        # single canonical candidate.
        return resolve_platform_sku(
            tenant,
            record.get("platform_sku")
            or record.get("platform_sku_code")
            or record.get("seller_sku")
            or record.get("sku"),
            new_skus,
            legacy_skus,
        ), None
    except SKUResolutionError as exc:
        return None, exc


def _site_for(tenant, platform, store, record):
    row = {
        "country_code": _text(record.get("country_code") or record.get("region")),
        "site": _text(record.get("site") or record.get("site_code")),
    }
    sites = list(CountrySiteMaster.objects.filter(tenant=tenant))
    return _resolve_site(tenant, platform, store, row, sites)


def _actor_for(sync_job, actor=None):
    candidate = actor or getattr(sync_job.integration_config, "created_by", None)
    if candidate is None or candidate.tenant_id != sync_job.tenant_id:
        return None
    return candidate


def _as_aware_datetime(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = _parse_datetime(value)
    if not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _is_stale_snapshot(existing, incoming_updated_at):
    current = _as_aware_datetime(existing.platform_updated_at)
    incoming = _as_aware_datetime(incoming_updated_at)
    return bool(current and incoming and incoming < current)


def _is_status_only_record(record):
    """Recognize an explicit provider status-only product snapshot.

    TikTok can emit FREEZE/DELETED events without the complete product
    payload.  The adapter owns deciding when a provider event is status-only;
    this boundary accepts the stable boolean and a small set of normalized
    aliases so older adapters can roll forward without re-enabling a broad
    status-based heuristic.
    """

    value = record.get("status_only", record.get("status_only_snapshot", False))
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "status_only"}
    return bool(value)


def _status_only_product_id(record):
    return _text(record.get("platform_product_id") or record.get("product_id"))


def _status_only_variant_id(record):
    return _text(
        record.get("platform_variant_id")
        or record.get("variant_id")
        or record.get("sku_id")
    )


def _status_only_status(record):
    return _text(
        record.get("sales_status")
        or record.get("platform_status")
        or record.get("status")
    )


def _status_only_updated_at(record):
    return record.get("platform_updated_at") or record.get("updated_at") or record.get("source_updated_at")


def _status_only_audit(
    sync_job,
    *,
    actor,
    platform,
    store,
    product_id,
    variant_id,
    result,
    reason,
    action,
):
    """Record status-only skips/updates without exposing source credentials."""

    if actor is None:
        return
    IntegrationAuditLog.objects.create(
        tenant=sync_job.tenant,
        integration_config=sync_job.integration_config,
        store_authorization=getattr(sync_job, "store_authorization", None),
        action=action,
        actor=actor,
        result=result,
        masked_detail={
            "platform": platform.code,
            "store_id": store.id,
            "platform_product_id": product_id,
            "platform_variant_id": variant_id,
            "reason": reason,
            "status_only": True,
        },
    )


def _upsert_status_only_product(*, sync_job, platform, store, record, actor):
    """Apply a TikTok status-only snapshot to existing product details.

    TikTok FREEZE/DELETED notifications may contain only a product ID.  When
    no variant ID is present, every already-ingested variant under that exact
    authorized product is eligible for a status/time update.  The function
    never creates a detail, resolves a SKU, or mutates a mapping.
    """

    tenant = sync_job.tenant
    product_id = _status_only_product_id(record)
    variant_id = _status_only_variant_id(record)
    status = _status_only_status(record)
    incoming_updated_at = _status_only_updated_at(record)
    idempotency_key = f"{sync_job.id}:{platform.code}:{store.id}:status-only:{product_id}:{variant_id or 'all'}"

    def skipped(reason, *, details=None, result_code=None):
        details = list(details or [])
        _status_only_audit(
            sync_job,
            actor=actor,
            platform=platform,
            store=store,
            product_id=product_id,
            variant_id=variant_id,
            result=IntegrationAuditLog.Result.BLOCKED,
            reason=reason,
            action="platform_product_status_only_skip",
        )
        mapping = _mapping_for_detail(details[0]) if details else None
        return {
            "action": "skipped",
            "idempotency_key": idempotency_key,
            "platform_product_detail_id": details[0].id if details else None,
            "platform_product_detail_ids": [detail.id for detail in details],
            "mapping_id": mapping.id if mapping is not None else None,
            "mapping_status": mapping.status if mapping is not None else None,
            "mapping_state": "status_only_skip",
            "sku_state": "unchanged",
            "result_code": result_code or reason,
            "status_only": True,
        }

    if not product_id:
        return skipped("missing_platform_product_id", result_code="STATUS_ONLY_PRODUCT_ID_REQUIRED")

    details_query = (
        PlatformProductDetail.objects.select_for_update()
        .select_related("platform", "store", "internal_sku")
        .filter(
            tenant=tenant,
            platform=platform,
            store=store,
            platform_product_id=product_id,
        )
    )
    if variant_id:
        details_query = details_query.filter(platform_variant_id=variant_id)
    details = list(details_query.order_by("id"))
    if not details:
        if variant_id:
            # Distinguish an existing variant belonging to another product so
            # a status event cannot accidentally update it by variant ID.
            same_variant = PlatformProductDetail.objects.filter(
                tenant=tenant,
                platform=platform,
                store=store,
                platform_variant_id=variant_id,
            ).first()
            if same_variant is not None:
                return skipped(
                    "platform_product_id_mismatch",
                    details=[same_variant],
                    result_code="STATUS_ONLY_PRODUCT_MISMATCH",
                )
            return skipped("unknown_variant", result_code="STATUS_ONLY_UNKNOWN_VARIANT")
        return skipped("unknown_product", result_code="STATUS_ONLY_UNKNOWN_PRODUCT")

    try:
        incoming_updated = _as_aware_datetime(incoming_updated_at)
    except (TypeError, ValueError):
        return skipped(
            "invalid_platform_updated_at",
            details=details,
            result_code="STATUS_ONLY_INVALID_TIMESTAMP",
        )

    changed_details = []
    stale_details = []
    for detail in details:
        if _is_stale_snapshot(detail, incoming_updated):
            stale_details.append(detail)
            continue
        changed = []
        if status and detail.sales_status != status:
            detail.sales_status = status
            changed.append("sales_status")
        if incoming_updated is not None and detail.platform_updated_at != incoming_updated:
            detail.platform_updated_at = incoming_updated
            changed.append("platform_updated_at")
        if changed:
            detail.save(update_fields=[*changed, "updated_at"])
            changed_details.append(detail)

    if not changed_details and stale_details and len(stale_details) == len(details):
        _status_only_audit(
            sync_job,
            actor=actor,
            platform=platform,
            store=store,
            product_id=product_id,
            variant_id=variant_id,
            result=IntegrationAuditLog.Result.BLOCKED,
            reason="stale_platform_snapshot",
            action="platform_product_status_only_skip",
        )
        mapping = _mapping_for_detail(details[0])
        return {
            "action": "skipped",
            "idempotency_key": idempotency_key,
            "platform_product_detail_id": details[0].id,
            "platform_product_detail_ids": [detail.id for detail in details],
            "mapping_id": mapping.id if mapping is not None else None,
            "mapping_status": mapping.status if mapping is not None else None,
            "mapping_state": "stale_snapshot",
            "sku_state": "stale",
            "result_code": "STALE_PLATFORM_SNAPSHOT",
            "stale_snapshot": True,
            "status_only": True,
        }

    _status_only_audit(
        sync_job,
        actor=actor,
        platform=platform,
        store=store,
        product_id=product_id,
        variant_id=variant_id,
        result=IntegrationAuditLog.Result.SUCCESS,
        reason="status_only_updated" if changed_details else "status_only_unchanged",
        action="platform_product_status_only_update",
    )
    mapping = _mapping_for_detail(details[0])
    return {
        "action": "updated" if changed_details else "skipped",
        "idempotency_key": idempotency_key,
        "platform_product_detail_id": details[0].id,
        "platform_product_detail_ids": [detail.id for detail in details],
        "updated_detail_count": len(changed_details),
        "stale_detail_count": len(stale_details),
        "mapping_id": mapping.id if mapping is not None else None,
        "mapping_status": mapping.status if mapping is not None else None,
        "mapping_state": "status_only",
        "sku_state": "unchanged",
        "result_code": "" if changed_details else "STATUS_ONLY_UNCHANGED",
        "status_only": True,
    }


def _mapping_store_for(tenant, platform, store, *, sync_job=None, actor=None):
    platform_value = _text(platform.platform_type or platform.code).lower()
    if platform_value not in {"shopee", "tiktok"}:
        return None, "mapping_platform_not_supported"
    rows = list(
        MarketplaceStoreMapping.objects.filter(
            tenant=tenant,
            store=store,
            platform=platform_value,
            status=MarketplaceStoreMapping.Status.ACTIVE,
        ).select_related("authorization__integration_config").order_by("id")[:2]
    )
    if len(rows) > 1:
        return None, "multiple_active_store_mappings"
    current_authorization = getattr(sync_job, "store_authorization", None) if sync_job is not None else None
    if not rows:
        # An active authorization is the authoritative external identity.  If
        # the operator has not yet materialized the local store mapping, derive
        # it through the existing service rather than matching by store name.
        authorization = current_authorization
        if (
            authorization is not None
            and actor is not None
            and authorization.status == authorization.Status.ACTIVE
            and authorization.store_id == store.id
            and authorization.platform == platform_value
        ):
            from .store_mapping_service import create_store_mapping
            try:
                return create_store_mapping(
                    tenant=tenant,
                    actor=actor,
                    store=store,
                    authorization=authorization,
                    mapping_source=MarketplaceStoreMapping.MappingSource.OAUTH_CALLBACK,
                    store_timezone="",
                    currency=store.currency,
                ), ""
            except StateConflict:
                # Another worker may have won the unique external identity;
                # re-read the active mapping and continue idempotently.
                rows = list(
                    MarketplaceStoreMapping.objects.filter(
                        tenant=tenant,
                        store=store,
                        platform=platform_value,
                        status=MarketplaceStoreMapping.Status.ACTIVE,
                    ).select_related("authorization__integration_config").order_by("id")[:2]
                )
                if len(rows) == 1:
                    return rows[0], ""
        inactive = MarketplaceStoreMapping.objects.filter(
            tenant=tenant,
            store=store,
            platform=platform_value,
            status=MarketplaceStoreMapping.Status.INACTIVE,
        ).exists()
        if inactive:
            return None, "store_mapping_inactive"
        return None, "store_mapping_missing"
    mapping = rows[0]
    # An active local row is not sufficient on its own.  A revoked/expired
    # authorization must not keep feeding the product mapping chain, and an
    # authorization for another external shop must not be reused merely
    # because it points at the same internal store.  Compare the provider's
    # stable identity, rather than a display name or local store code.
    mapping_authorization = mapping.authorization
    if mapping_authorization.status != mapping_authorization.Status.ACTIVE:
        return None, "store_mapping_authorization_inactive"
    if current_authorization is not None:
        if (
            current_authorization.status != current_authorization.Status.ACTIVE
            or current_authorization.tenant_id != tenant.id
            or current_authorization.platform != platform_value
            or current_authorization.store_id != store.id
            or mapping.platform_store_id != current_authorization.platform_store_id
            or mapping.platform_identity_key != current_authorization.platform_identity_key
            or mapping_authorization.platform_store_id != current_authorization.platform_store_id
            or mapping_authorization.platform_identity_key != current_authorization.platform_identity_key
        ):
            return None, "store_mapping_identity_mismatch"
    return mapping, ""


def _mapping_for_detail(detail, store_mapping=None):
    mapping = (
        MarketplaceProductMapping.objects.select_for_update()
        .select_related("sku", "platform_detail", "store_mapping__authorization__integration_config")
        .filter(
            tenant=detail.tenant,
            platform_detail=detail,
            store_mapping__tenant=detail.tenant,
            store_mapping__store=detail.store,
        )
        .first()
    )
    if mapping is not None or store_mapping is None:
        return mapping
    return (
        MarketplaceProductMapping.objects.select_for_update()
        .select_related("sku", "platform_detail", "store_mapping__authorization__integration_config")
        .filter(
            tenant=detail.tenant,
            store_mapping=store_mapping,
            platform_variant_id=detail.platform_variant_id,
        )
        .first()
    )


def _set_mapping_result(mapping, *, actor, code, conflict=False, audit_detail=None):
    """Keep an unresolved reason on a mapping without changing its SKU link.

    A conflict is an explicit state transition for operator review; the
    canonical SKU/detail association itself is never replaced by a source
    proposal.  Callers must skip inactive mappings before reaching this
    helper.
    """

    target_status = (
        MarketplaceProductMapping.Status.CONFLICT
        if conflict
        else mapping.status
    )
    if mapping.result_code == code and mapping.status == target_status:
        return mapping
    previous_status = mapping.status
    mapping.status = target_status
    mapping.result_code = code
    if actor is not None:
        mapping.updated_by = actor
    mapping.last_verified_at = timezone.now()
    fields = ["status", "result_code", "last_verified_at", "updated_at"]
    if actor is not None:
        fields.insert(1, "updated_by")
    with product_mapping_service_write():
        mapping.save(update_fields=fields)
    _product_mapping_audit(
        mapping.tenant,
        mapping.store_mapping.authorization.integration_config,
        actor,
        "product_mapping_ingestion_issue",
        IntegrationAuditLog.Result.BLOCKED,
        {
            "platform_variant_id": mapping.platform_variant_id,
            "result_code": code,
            "previous_status": previous_status,
            "status": mapping.status,
            **(audit_detail or {}),
        },
    )
    return mapping


def _link_mapping(*, tenant, platform, store, detail, sku, actor, sync_job=None, resolution_error=None):
    """Link the canonical detail to the existing mapping workflow.

    Deterministic API matches are represented as a narrowly auditable
    ``api_exact_match`` mapping with confidence 100.  Fuzzy or incomplete
    records remain unmapped/conflicted and are available through the existing
    mapping options endpoint.  Existing inactive mappings are stopped
    histories and are never reactivated by ingestion.
    """

    store_mapping, mapping_code = _mapping_store_for(
        tenant,
        platform,
        store,
        sync_job=sync_job,
        actor=actor,
    )
    if store_mapping is None:
        return None, mapping_code
    mapping = _mapping_for_detail(detail, store_mapping)
    if mapping is not None and mapping.status == MarketplaceProductMapping.Status.INACTIVE:
        return mapping, "mapping_inactive"
    if mapping is None:
        mapping = create_product_mapping(
            tenant=tenant,
            actor=actor,
            store_mapping=store_mapping,
            platform_product_id=detail.platform_product_id,
            platform_variant_id=detail.platform_variant_id,
            platform_sku=detail.platform_sku,
            platform_detail=detail,
            mapping_source=MarketplaceProductMapping.MappingSource.SYNTHETIC_DISCOVERY,
        )
    elif mapping.platform_detail_id and mapping.platform_detail_id != detail.id:
        return _set_mapping_result(
            mapping,
            actor=actor,
            code="PLATFORM_DETAIL_CONFLICT",
            conflict=True,
            audit_detail={
                "existing_platform_detail_id": mapping.platform_detail_id,
                "incoming_platform_detail_id": detail.id,
            },
        ), "PLATFORM_DETAIL_CONFLICT"
    elif (
        mapping.sku_id
        and detail.internal_sku_id
        and mapping.sku_id != detail.internal_sku_id
    ):
        return _set_mapping_result(
            mapping,
            actor=actor,
            code="SKU_SOURCE_CONFLICT",
            conflict=True,
            audit_detail={
                "existing_sku_id": mapping.sku_id,
                "proposed_sku_id": detail.internal_sku_id,
            },
        ), "SKU_SOURCE_CONFLICT"

    if mapping.platform_detail_id is None:
        mapping.platform_detail = detail
        with product_mapping_service_write():
            mapping.save(update_fields=["platform_detail", "updated_at"])

    if resolution_error is not None:
        code = "SKU_SOURCE_CONFLICT" if resolution_error.state == "conflict" else "SKU_SOURCE_PENDING"
        return _set_mapping_result(
            mapping,
            actor=actor,
            code=code,
            conflict=resolution_error.state == "conflict",
            audit_detail={
                "resolution_code": resolution_error.code,
                **(
                    {"proposed_sku_id": resolution_error.proposed_sku_id}
                    if getattr(resolution_error, "proposed_sku_id", None)
                    else {}
                ),
                **(
                    {"proposed_old_sku_id": resolution_error.proposed_old_sku_id}
                    if getattr(resolution_error, "proposed_old_sku_id", None)
                    else {}
                ),
                **(
                    {"proposed_platform_product_id": resolution_error.proposed_platform_product_id}
                    if getattr(resolution_error, "proposed_platform_product_id", None)
                    else {}
                ),
                **(
                    {"proposed_platform_sku": resolution_error.proposed_platform_sku}
                    if getattr(resolution_error, "proposed_platform_sku", None)
                    else {}
                ),
            },
        ), code

    if sku is None:
        return _set_mapping_result(mapping, actor=actor, code="SKU_SOURCE_PENDING"), "SKU_SOURCE_PENDING"

    if mapping.status == MarketplaceProductMapping.Status.MAPPED:
        if mapping.sku_id == sku.id and detail.internal_sku_id == sku.id:
            return mapping, "matched"
        # A confirmed mapping is an operator decision.  Keep both the mapping
        # and the canonical detail untouched and surface the source conflict.
        return _set_mapping_result(
            mapping,
            actor=actor,
            code="SKU_SOURCE_CONFLICT",
            conflict=True,
        ), "SKU_SOURCE_CONFLICT"
    if mapping.status == MarketplaceProductMapping.Status.CONFLICT:
        return mapping, "mapping_conflict"
    if mapping.status == MarketplaceProductMapping.Status.INACTIVE:
        return mapping, "mapping_inactive"
    try:
        mapped = auto_associate_product_mapping(mapping, actor=actor, sku=sku)
    except StateConflict as exc:
        # A same-store SKU collision is a source-data conflict, not a reason
        # to roll back the canonical platform detail or the whole sync page.
        # Leave the existing confirmed mapping untouched and keep this row in
        # the manual reconciliation queue.
        code = "SKU_ALREADY_MAPPED" if "already mapped" in str(exc).lower() else "API_EXACT_MATCH_CONFLICT"
        return _set_mapping_result(mapping, actor=actor, code=code, conflict=True), code
    return mapped, "matched"


def _incoming_values(*, tenant, platform, store, site, record, sku):
    created_at = record.get("platform_created_at")
    updated_at = record.get("platform_updated_at") or record.get("updated_at")
    if isinstance(created_at, str) and created_at.strip():
        created_at = _parse_datetime(created_at)
    if isinstance(updated_at, str) and updated_at.strip():
        updated_at = _parse_datetime(updated_at)
    return {
        "tenant": tenant,
        "platform": platform,
        "store": store,
        "site": site,
        "platform_product_id": _text(record.get("platform_product_id") or record.get("product_id")),
        "platform_variant_id": _text(record.get("platform_variant_id") or record.get("variant_id") or record.get("sku_id")),
        "platform_sku": _text(record.get("platform_sku") or record.get("seller_sku") or record.get("platform_sku_code")),
        "source_old_sku_code": _clean_sku(
            record.get("source_old_sku_code") or record.get("old_sku_code") or record.get("legacy_sku_code")
        ),
        "internal_sku": sku,
        "title": _text(record.get("title") or record.get("product_name") or record.get("name")),
        "variant": _text(record.get("variant") or record.get("variant_name") or record.get("sku_name")),
        "category_l1": _text(record.get("category_l1")),
        "category_l2": _text(record.get("category_l2")),
        "category_l3": _text(record.get("category_l3")),
        "sku_prefix": _text(record.get("sku_prefix")),
        "shop_abbr": _text(record.get("shop_abbr")),
        "sales_status": _text(record.get("sales_status") or record.get("status")),
        "owner": _text(record.get("owner")),
        "leader": _text(record.get("leader")),
        "platform_created_at": created_at,
        "platform_updated_at": updated_at,
        "source": INGESTION_SOURCE,
    }


@transaction.atomic
def upsert_platform_product(sync_job, normalized_record, *, actor=None):
    """Persist one normalized API product/variant and return adapter result data.

    ``normalized_record`` is intentionally platform-neutral.  Required keys
    are ``platform_variant_id`` and a store subject (normally supplied by
    ``sync_job.store_authorization``); product ID, platform SKU, title and
    either/both internal SKU code columns are optional.  The idempotency key
    is tenant + platform + store + variant, never a global SKU.
    """

    tenant = sync_job.tenant
    platform = _platform_for(sync_job, normalized_record)
    store = _store_for(sync_job, platform, normalized_record)
    actor = _actor_for(sync_job, actor)
    if _is_status_only_record(normalized_record):
        # Status-only snapshots are intentionally handled before site/SKU
        # resolution.  They are partial provider facts, not a new product
        # identity, and therefore must never create a detail or mapping.
        return _upsert_status_only_product(
            sync_job=sync_job,
            platform=platform,
            store=store,
            record=normalized_record,
            actor=actor,
        )
    variant_id = _text(
        normalized_record.get("platform_variant_id")
        or normalized_record.get("variant_id")
        or normalized_record.get("sku_id")
    )
    if not variant_id:
        raise ValidationError({"platform_variant_id": "平台商品同步缺少变体 ID。"})
    site = _site_for(tenant, platform, store, normalized_record)
    sku_cache = getattr(sync_job, "_platform_product_sku_cache", None)
    if sku_cache is None:
        sku_cache = build_sku_resolution_caches(tenant)
        # Sync workers reuse the same SyncJob instance for a page/run.  Keep
        # this catalogue-sized allocation once per run rather than scanning
        # all tenant SKUs for every variant.
        setattr(sync_job, "_platform_product_sku_cache", sku_cache)
    sku, resolution_error = _resolve_ingestion_sku(
        tenant,
        normalized_record,
        *sku_cache,
    )
    values = _incoming_values(
        tenant=tenant,
        platform=platform,
        store=store,
        site=site,
        record=normalized_record,
        sku=sku,
    )
    values["platform_variant_id"] = variant_id

    detail = (
        PlatformProductDetail.objects.select_for_update()
        .select_related("internal_sku", "platform", "store")
        .filter(
            tenant=tenant,
            platform=platform,
            store=store,
            platform_variant_id=variant_id,
        )
        .first()
    )
    created = detail is None
    existing_sku_id = detail.internal_sku_id if detail is not None else None
    detail_changed = False
    if detail is None:
        detail = PlatformProductDetail(**values)
        detail.save()
    else:
        if _is_stale_snapshot(detail, values["platform_updated_at"]):
            mapping = _mapping_for_detail(detail)
            return {
                "action": "skipped",
                "idempotency_key": f"{sync_job.id}:{platform.code}:{store.id}:{variant_id}",
                "platform_product_detail_id": detail.id,
                "mapping_id": mapping.id if mapping is not None else None,
                "mapping_status": mapping.status if mapping is not None else None,
                "mapping_state": "stale_snapshot",
                "sku_state": "stale",
                "result_code": "STALE_PLATFORM_SNAPSHOT",
                "stale_snapshot": True,
            }
        mapping = _mapping_for_detail(detail)
        controlled_mapping = bool(mapping is not None and mapping.status != MarketplaceProductMapping.Status.INACTIVE)
        existing_sku_conflict = False
        identity_conflict = False
        changed = []
        for field in DETAIL_FIELDS:
            incoming = values[field]
            if field in {"platform_created_at", "platform_updated_at"} and incoming is None:
                continue
            if field in {"platform_product_id", "platform_sku", "source_old_sku_code", "internal_sku"}:
                if (
                    field in {"platform_product_id", "platform_sku", "source_old_sku_code"}
                    and not incoming
                    and getattr(detail, field)
                ):
                    # Read-only provider payloads may omit optional identity
                    # columns.  Preserve a known fact instead of treating an
                    # absent field as a replacement/conflict.
                    continue
                # The provider's product/SKU identity is protected while a
                # mapping is controlled.  The explicit old-code column is a
                # source fact, however, so it may be refreshed and then be
                # surfaced as a dual-code conflict when it no longer agrees
                # with the canonical SKU.
                if (
                    controlled_mapping
                    and field in {"platform_product_id", "platform_sku"}
                    and getattr(detail, field)
                    and getattr(detail, field) != incoming
                ):
                    identity_conflict = True
                    continue
                if field == "internal_sku" and incoming is None and detail.internal_sku_id:
                    continue
                if field == "internal_sku" and detail.internal_sku_id and incoming and detail.internal_sku_id != incoming.id:
                    existing_sku_conflict = True
                    continue
            current = detail.internal_sku_id if field == "internal_sku" else getattr(detail, field)
            incoming_value = incoming.id if field == "internal_sku" and incoming is not None else incoming
            if current != incoming_value:
                setattr(detail, field, incoming)
                changed.append(field)
        if changed:
            detail.save(update_fields=[*changed, "updated_at"])
            detail_changed = True

        # Once a canonical detail has an internal SKU, an API refresh may
        # propose a different candidate but must not switch the established
        # identity before manual review.  Convert that proposal into the same
        # conflict path used by new/legacy code mismatches.
        if (existing_sku_conflict or identity_conflict) and resolution_error is None:
            resolution_error = SKUResolutionError(
                "平台商品已存在已建立的内部身份，新的平台身份需要人工复核。",
                code="existing_identity_conflict" if identity_conflict else "existing_sku_conflict",
                state="conflict",
            )
            if sku is not None:
                resolution_error.proposed_sku_id = sku.id
            if identity_conflict:
                resolution_error.proposed_platform_product_id = values["platform_product_id"]
                resolution_error.proposed_platform_sku = values["platform_sku"]

    mapping = None
    mapping_state = "unavailable"
    if actor is not None:
        mapping, mapping_state = _link_mapping(
            tenant=tenant,
            platform=platform,
            store=store,
            detail=detail,
            sku=sku,
            actor=actor,
            sync_job=sync_job,
            resolution_error=resolution_error,
        )

    if resolution_error is not None:
        sku_state = resolution_error.state
        result_code = resolution_error.code
    elif existing_sku_id and sku is not None and existing_sku_id != sku.id:
        sku_state = "conflict"
        result_code = "EXISTING_SKU_CONFLICT"
    elif mapping_state in {
        "mapping_conflict",
        "API_EXACT_MATCH_CONFLICT",
        "SKU_ALREADY_MAPPED",
        "SKU_SOURCE_CONFLICT",
        "PLATFORM_DETAIL_CONFLICT",
    }:
        # The source SKU itself may be exact, but a prior mapping decision or
        # a same-store uniqueness guard still requires manual review.
        sku_state = "conflict"
        result_code = mapping_state.upper()
    elif mapping_state not in {"matched", "unavailable"}:
        # An exact SKU without a usable store mapping (for example an
        # inactive authorization) is still retained in the platform detail,
        # but cannot be presented as a complete association.
        sku_state = "conflict" if sku is not None else "pending"
        result_code = mapping_state.upper()
    else:
        sku_state = "matched" if sku is not None else "pending"
        result_code = "" if sku is not None else "SKU_SOURCE_PENDING"

    return {
        "action": "created" if created else "updated" if detail_changed else "skipped",
        "idempotency_key": f"{sync_job.id}:{platform.code}:{store.id}:{variant_id}",
        "platform_product_detail_id": detail.id,
        "mapping_id": mapping.id if mapping is not None else None,
        "mapping_status": mapping.status if mapping is not None else None,
        "mapping_state": mapping_state,
        "sku_state": sku_state,
        "result_code": result_code,
    }


# Adapter-facing alias kept explicit for callers that use the model name.
upsert_platform_product_detail = upsert_platform_product
