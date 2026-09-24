import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.integrations.models import MarketplaceStoreAuthorization, SyncRun

from .contracts import normalize_finance_transaction_record
from .models import PlatformFinanceTransaction
from .normalization import normalize_fee


@dataclass(frozen=True)
class FinanceIngestionResult:
    instance: PlatformFinanceTransaction
    action: str


def _canonical_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc(value):
    parsed = value if isinstance(value, datetime) else parse_datetime(str(value or ""))
    if parsed is None or parsed.tzinfo is None:
        raise ValidationError({"occurred_at_utc": "A timezone-aware timestamp is required."})
    return parsed.astimezone(UTC)


def _match_order(*, tenant, store, payload):
    external_order_id = payload.get("external_order_id") or ""
    if not external_order_id:
        return None, None, PlatformFinanceTransaction.MatchStatus.UNMATCHED
    order = SalesOrder.objects.filter(
        tenant=tenant,
        store=store,
        external_order_id=external_order_id,
    ).first()
    if order is None:
        return None, None, PlatformFinanceTransaction.MatchStatus.UNMATCHED

    def unique_line(queryset):
        candidates = list(queryset.order_by("id")[:2])
        if len(candidates) == 1:
            return candidates[0], False
        return None, len(candidates) > 1

    line_id = payload.get("external_order_item_id") or ""
    if line_id:
        item, conflict = unique_line(order.items.filter(external_line_id=line_id))
        if item:
            return order, item, PlatformFinanceTransaction.MatchStatus.MATCHED
        if conflict:
            return order, None, PlatformFinanceTransaction.MatchStatus.CONFLICT

    variant_id = payload.get("platform_variant_id") or ""
    if variant_id:
        item, conflict = unique_line(order.items.filter(platform_variant_id=variant_id))
        if item:
            return order, item, PlatformFinanceTransaction.MatchStatus.MATCHED
        if conflict:
            return order, None, PlatformFinanceTransaction.MatchStatus.CONFLICT

    seller_sku = payload.get("seller_sku") or ""
    if seller_sku:
        item, conflict = unique_line(order.items.filter(seller_sku=seller_sku))
        if item:
            return order, item, PlatformFinanceTransaction.MatchStatus.MATCHED
        if conflict:
            return order, None, PlatformFinanceTransaction.MatchStatus.CONFLICT
    return order, None, PlatformFinanceTransaction.MatchStatus.ORDER_ONLY


@transaction.atomic
def upsert_finance_transaction(*, tenant, store, authorization, source_run, payload, raw_envelope=None):
    if store.tenant_id != tenant.id:
        raise ValidationError({"store": "A tenant-owned store is required."})
    if not isinstance(authorization, MarketplaceStoreAuthorization):
        raise ValidationError({"authorization": "A marketplace store authorization is required."})
    platform = str(authorization.platform or "").lower()
    if (
        authorization.tenant_id != tenant.id
        or authorization.store_id != store.id
        or platform not in {"lazada", "shopee", "tiktok"}
        or store.platform.platform_type != platform
        or authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE
    ):
        raise ValidationError({"authorization": "An active same-tenant marketplace authorization is required."})
    if not isinstance(source_run, SyncRun) or source_run.tenant_id != tenant.id:
        raise ValidationError({"source_run": "A same-tenant SyncRun is required."})
    if (
        source_run.sync_job.resource_type != "settlement_bill"
        or source_run.sync_job.store_authorization_id != authorization.id
        or source_run.sync_job.integration_config.platform != platform
    ):
        raise ValidationError({"source_run": "SyncRun must use this marketplace settlement authorization."})

    normalized = normalize_finance_transaction_record(payload)
    fee = normalize_fee(normalized["raw_fee_name"], normalized["raw_amount"])
    occurred_at = _utc(normalized["occurred_at_utc"])
    try:
        business_zone = ZoneInfo(store.timezone)
    except Exception as exc:
        raise ValidationError({"store": "Store timezone is invalid."}) from exc
    sales_order, sales_order_item, match_status = _match_order(
        tenant=tenant,
        store=store,
        payload=normalized,
    )
    raw_envelope = raw_envelope or source_run.raw_envelopes.order_by("-sequence").first()
    hash_payload = {
        **normalized,
        "fee_code": fee["fee_code"],
        "fee_category": fee["fee_category"],
        "signed_amount": str(fee["signed_amount"]),
        "normalization_version": fee["normalization_version"],
    }
    payload_hash = _canonical_hash(hash_payload)
    defaults = {
        "platform": platform,
        "authorization": authorization,
        "source_run": source_run,
        "raw_envelope": raw_envelope,
        "external_transaction_id": normalized["external_transaction_id"],
        "external_order_id": normalized["external_order_id"],
        "external_order_item_id": normalized["external_order_item_id"],
        "sales_order": sales_order,
        "sales_order_item": sales_order_item,
        "seller_sku": normalized["seller_sku"],
        "platform_variant_id": normalized["platform_variant_id"],
        "raw_fee_name": fee["raw_fee_name"],
        "fee_code": fee["fee_code"],
        "fee_category": fee["fee_category"],
        "raw_amount": Decimal(str(fee["raw_amount"])),
        "signed_amount": Decimal(str(fee["signed_amount"])),
        "currency": normalized["currency"],
        "occurred_at_utc": occurred_at,
        "business_date": occurred_at.astimezone(business_zone).date(),
        "match_status": match_status,
        "normalization_version": fee["normalization_version"],
        "payload_hash": payload_hash,
    }
    existing = PlatformFinanceTransaction.objects.select_for_update().filter(
        tenant=tenant,
        store=store,
        source_key=normalized["source_key"],
    ).first()
    if existing is None:
        instance = PlatformFinanceTransaction.objects.create(
            tenant=tenant,
            store=store,
            source_key=normalized["source_key"],
            **defaults,
        )
        return FinanceIngestionResult(instance=instance, action="created")
    relation_changed = (
        existing.sales_order_id != getattr(sales_order, "id", None)
        or existing.sales_order_item_id != getattr(sales_order_item, "id", None)
        or existing.match_status != match_status
    )
    if existing.payload_hash == payload_hash and not relation_changed:
        return FinanceIngestionResult(instance=existing, action="skipped")
    for field_name, value in defaults.items():
        setattr(existing, field_name, value)
    existing.save(update_fields=[*defaults.keys(), "updated_at"])
    return FinanceIngestionResult(instance=existing, action="updated")


def rematch_unmatched_transactions(*, tenant, store):
    updated = 0
    queryset = PlatformFinanceTransaction.objects.filter(
        tenant=tenant,
        store=store,
        match_status__in=[
            PlatformFinanceTransaction.MatchStatus.UNMATCHED,
            PlatformFinanceTransaction.MatchStatus.ORDER_ONLY,
            PlatformFinanceTransaction.MatchStatus.CONFLICT,
        ],
    ).select_related("authorization", "source_run")
    for transaction_record in queryset.iterator():
        result = upsert_finance_transaction(
            tenant=tenant,
            store=store,
            authorization=transaction_record.authorization,
            source_run=transaction_record.source_run,
            raw_envelope=transaction_record.raw_envelope,
            payload={
                "contract_version": "finance_transaction.v1",
                "source_key": transaction_record.source_key,
                "external_transaction_id": transaction_record.external_transaction_id,
                "external_order_id": transaction_record.external_order_id,
                "external_order_item_id": transaction_record.external_order_item_id,
                "seller_sku": transaction_record.seller_sku,
                "platform_variant_id": transaction_record.platform_variant_id,
                "raw_fee_name": transaction_record.raw_fee_name,
                "raw_amount": str(transaction_record.raw_amount),
                "currency": transaction_record.currency,
                "occurred_at_utc": transaction_record.occurred_at_utc.isoformat(),
            },
        )
        updated += result.action == "updated"
    return updated


__all__ = ["FinanceIngestionResult", "rematch_unmatched_transactions", "upsert_finance_transaction"]
