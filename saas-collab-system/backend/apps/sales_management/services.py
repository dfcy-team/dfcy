import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.commerce.sales_sku_mapping import audit_sku_links, link_order_skus, order_sku_fields, resolve_sales_skus
from apps.integrations.models import SyncRun
from apps.masterdata.models import StoreMaster
from apps.reports.export_services import create_export_request


def _canonical_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc(value, field_name):
    parsed = value if isinstance(value, datetime) else parse_datetime(str(value or ""))
    if parsed is None or parsed.tzinfo is None:
        raise ValidationError({field_name: "A timezone-aware timestamp is required."})
    return parsed.astimezone(UTC)


def _decimal(value):
    return Decimal(str(value or 0))


def _optional_utc(value, field_name):
    return _utc(value, field_name) if value not in (None, "") else None


@transaction.atomic
def upsert_normalized_order(*, tenant, payload, source_run):
    """Idempotently persist a reviewed canonical order record.

    Older platform events never overwrite a record with a newer source timestamp.
    The caller must supply an existing SyncRun; no second ingestion/staging track is
    created here.
    """
    if not isinstance(source_run, SyncRun) or source_run.tenant_id != tenant.id:
        raise ValidationError({"source_run": "A same-tenant SyncRun is required."})
    if source_run.sync_job.resource_type != "sales_order":
        raise ValidationError({"source_run": "SyncRun must use the sales_order resource type."})
    store_reference = payload.get("store_id") or payload.get("store_code")
    stores = StoreMaster.objects.filter(tenant=tenant)
    store = stores.filter(pk=store_reference).first() if str(store_reference).isdigit() else stores.filter(code=store_reference).first()
    if store is None:
        raise ValidationError({"store_id": "A tenant-owned store is required."})
    if store.platform.platform_type != source_run.sync_job.integration_config.platform:
        raise ValidationError({"source_run": "SyncRun platform must match the order store."})

    external_order_id = str(payload.get("external_order_id") or payload.get("source_order_id") or "").strip()
    if not external_order_id:
        raise ValidationError({"external_order_id": "External order ID is required."})
    source_updated_at = _utc(payload.get("updated_at_utc") or payload.get("source_updated_at"), "updated_at_utc")
    created_at = _utc(payload.get("created_at_utc") or payload.get("ordered_at"), "created_at_utc")
    lookup = {
        "tenant": tenant,
        "platform": store.platform,
        "store": store,
        "external_order_id": external_order_id,
    }
    existing = SalesOrder.objects.select_for_update().filter(**lookup).first()
    if existing and existing.updated_at_utc > source_updated_at:
        return existing

    total = _decimal(payload.get("order_total_amount", payload.get("gross_amount", 0)))
    defaults = {
        "authorization": source_run.sync_job.integration_config,
        "source_run": source_run,
        "internal_sync_batch": None,
        "region": str(payload.get("region") or store.country_code),
        "raw_status": str(payload.get("raw_status") or payload.get("order_status") or "unknown"),
        "normalized_status": str(payload.get("normalized_status") or payload.get("order_status") or "pending"),
        "status_mapping_version": str(payload.get("status_mapping_version") or payload.get("contract_version") or "1.0"),
        "created_at_utc": created_at,
        "updated_at_utc": source_updated_at,
        "paid_at_utc": _optional_utc(payload.get("paid_at_utc"), "paid_at_utc"),
        "cancelled_at_utc": _optional_utc(payload.get("cancelled_at_utc"), "cancelled_at_utc"),
        "completed_at_utc": _optional_utc(payload.get("completed_at_utc"), "completed_at_utc"),
        "business_date": payload.get("business_date") or created_at.astimezone(UTC).date(),
        "currency": str(payload.get("currency") or store.currency).upper(),
        "subtotal_amount": _decimal(payload.get("subtotal_amount", total)),
        "seller_discount_amount": _decimal(payload.get("seller_discount_amount", payload.get("discount_amount", 0))),
        "platform_discount_amount": _decimal(payload.get("platform_discount_amount", 0)),
        "shipping_amount": _decimal(payload.get("shipping_amount", 0)),
        "tax_amount": _decimal(payload.get("tax_amount", 0)),
        "order_total_amount": total,
        "payload_hash": str(payload.get("payload_hash") or _canonical_hash(payload)),
    }
    if "delivered_at_utc" in payload:
        defaults["delivered_at_utc"] = _optional_utc(payload["delivered_at_utc"], "delivered_at_utc")
    if existing:
        for field_name, value in defaults.items():
            setattr(existing, field_name, value)
        existing.save(update_fields=defaults.keys())
        order = existing
    else:
        order = SalesOrder.objects.create(**lookup, **defaults)

    line_payloads = payload.get("lines") or []
    existing_lines = {line.external_line_id: line for line in order.items.select_for_update().prefetch_related(
        'refund_items', 'shipment_records')}
    resolved = resolve_sales_skus(tenant=tenant, store=store,
        codes=[line.get('seller_sku') or line.get('sku') for line in line_payloads], occurred_at=created_at)
    sku_changes = []
    sku_conflicts = []
    for index, line_payload in enumerate(line_payloads, start=1):
        external_line_id = str(line_payload.get("external_line_id") or line_payload.get("source_line_id") or index)
        line_defaults = {
            "platform_product_id": str(line_payload.get("platform_product_id") or ""),
            "platform_variant_id": str(line_payload.get("platform_variant_id") or ""),
            "seller_sku": str(line_payload.get("seller_sku") or line_payload.get("sku") or ""),
            "item_name_snapshot": str(line_payload.get("item_name_snapshot") or line_payload.get("product_name") or ""),
            "variation_snapshot": str(line_payload.get("variation_snapshot") or ""),
            "quantity": int(line_payload.get("quantity") or 0),
            "original_unit_price": _decimal(line_payload.get("original_unit_price", line_payload.get("unit_price", 0))),
            "sale_unit_price": _decimal(line_payload.get("sale_unit_price", line_payload.get("unit_price", 0))),
            "discount_amount": _decimal(line_payload.get("discount_amount", 0)),
            "tax_amount": _decimal(line_payload.get("tax_amount", 0)),
            "line_total_amount": _decimal(
                line_payload.get(
                    "line_total_amount",
                    _decimal(line_payload.get("unit_price", 0)) * int(line_payload.get("quantity") or 0),
                )
            ),
            "currency": str(line_payload.get("currency") or defaults["currency"]).upper(),
            "raw_line_status": str(line_payload.get("raw_line_status") or ""),
        }
        existing_line = existing_lines.get(external_line_id)
        candidate = resolved.get(line_defaults['seller_sku'].strip())
        if existing_line and candidate and existing_line.internal_sku_id not in (None, candidate.id):
            sku_conflicts.append({'model': 'SalesOrderItem', 'id': existing_line.id,
                                  'kept_internal_sku_id': existing_line.internal_sku_id,
                                  'proposed_internal_sku_id': candidate.id})
        sku_fields = order_sku_fields(existing_line, candidate)
        line_defaults.update(sku_fields)
        line, _ = SalesOrderItem.objects.update_or_create(
            sales_order=order,
            external_line_id=external_line_id,
            defaults=line_defaults,
        )
        if sku_fields:
            sku_changes.append({'model': 'SalesOrderItem', 'id': line.id, 'before_internal_sku_id': None,
                                'after_internal_sku_id': line.internal_sku_id})
    audit_sku_links(source_run, sku_changes, sku_conflicts)
    order._sku_link_count = len(sku_changes)
    from apps.integrations.order_field_mapping import apply_order_observations
    observations = payload.get('observed_fields') or {}
    if store.platform.platform_type == 'shopee' and isinstance(observations.get('platform_logistics'), dict):
        payload = {**payload, 'observed_fields': {**observations, 'platform_logistics': {
            **observations['platform_logistics'], 'source_run_id': source_run.id}}}
    apply_order_observations(order, payload)
    if order.normalized_status == "cancelled":
        from .aftersales import track_source
        required = payload.get("requires_physical_return")
        track_source(order, requires_return=required if type(required) is bool else None)
    return order


@transaction.atomic
def upsert_normalized_refund(*, tenant, payload, source_run):
    if not isinstance(source_run, SyncRun) or source_run.tenant_id != tenant.id:
        raise ValidationError({"source_run": "A same-tenant SyncRun is required."})
    if source_run.sync_job.resource_type != "refund_return":
        raise ValidationError({"source_run": "SyncRun must use the refund_return resource type."})

    store_reference = payload.get("store_id") or payload.get("store_code")
    stores = StoreMaster.objects.filter(tenant=tenant)
    store = (
        stores.filter(pk=store_reference).first()
        if str(store_reference).isdigit()
        else stores.filter(code=store_reference).first()
    )
    if store is None:
        raise ValidationError({"store_id": "A tenant-owned store is required."})
    if store.platform.platform_type != source_run.sync_job.integration_config.platform:
        raise ValidationError({"source_run": "SyncRun platform must match the refund store."})

    external_return_id = str(payload.get("external_return_id") or "").strip()
    if not external_return_id:
        raise ValidationError({"external_return_id": "External return ID is required."})
    updated_at = _utc(payload.get("updated_at_utc"), "updated_at_utc")
    lookup = {
        "tenant": tenant,
        "platform": store.platform,
        "store": store,
        "external_return_id": external_return_id,
    }
    existing = RefundReturn.objects.select_for_update().filter(**lookup).first()
    if existing and existing.updated_at_utc > updated_at:
        return existing

    external_order_id = str(payload.get("external_order_id") or "").strip()
    sales_order = None
    if external_order_id:
        sales_order = SalesOrder.objects.filter(
            tenant=tenant,
            platform=store.platform,
            store=store,
            external_order_id=external_order_id,
        ).first()
    order_links = link_order_skus(sales_order, source_run) if sales_order else 0
    defaults = {
        "sales_order": sales_order,
        "source_run": source_run,
        "external_refund_id": str(payload.get("external_refund_id") or ""),
        "case_type": str(payload.get("case_type") or "refund"),
        "raw_status": str(payload.get("raw_status") or "unknown"),
        "normalized_status": str(payload.get("normalized_status") or "pending"),
        "arbitration_status": str(payload.get("arbitration_status") or ""),
        "reason_code": str(payload.get("reason_code") or ""),
        "requested_at_utc": _utc(payload.get("requested_at_utc"), "requested_at_utc"),
        "updated_at_utc": updated_at,
        "completed_at_utc": _optional_utc(payload.get("completed_at_utc"), "completed_at_utc"),
        "currency": str(payload.get("currency") or store.currency).upper(),
        "refund_amount": _decimal(payload.get("refund_amount")),
        "refund_subtotal": _decimal(payload.get("refund_subtotal")),
        "refund_shipping_fee": _decimal(payload.get("refund_shipping_fee")),
        "refund_tax": _decimal(payload.get("refund_tax")),
        "requires_physical_return": payload.get("requires_physical_return"),
        "is_partial_quantity_return": payload.get("is_partial_quantity_return"),
        "is_refund_amount_adjusted": payload.get("is_refund_amount_adjusted"),
        "payload_hash": str(payload.get("payload_hash") or _canonical_hash(payload)),
    }
    if existing:
        for field_name, value in defaults.items():
            setattr(existing, field_name, value)
        existing.save(update_fields=defaults.keys())
        refund = existing
    else:
        refund = RefundReturn.objects.create(**lookup, **defaults)

    order_items = list(sales_order.items.all()) if sales_order else None
    resolved = resolve_sales_skus(tenant=tenant, store=store,
        codes=[item.get('seller_sku') for item in payload.get('items') or []],
        occurred_at=sales_order.created_at_utc if sales_order else _utc(payload.get('requested_at_utc'), 'requested_at_utc'))
    sku_changes = []
    existing_items = {item.external_return_item_id: item for item in refund.items.select_for_update()}
    for index, item_payload in enumerate(payload.get("items") or [], start=1):
        external_item_id = str(item_payload.get("external_return_item_id") or index)
        order_item = None
        external_order_item_id = str(item_payload.get("external_order_item_id") or "")
        if order_items is not None:
            product_id = str(item_payload.get("platform_product_id") or "")
            variant_id = str(item_payload.get("platform_variant_id") or "")
            seller_sku = str(item_payload.get("seller_sku") or "")
            candidates = [line for line in order_items
                          if product_id and variant_id
                          and line.platform_product_id == product_id and line.platform_variant_id == variant_id
                          and (not seller_sku or seller_sku in (
                              line.seller_sku, (line.source_details or {}).get('platform_model_sku')))]
            if store.platform.platform_type != 'shopee' and external_order_item_id:
                candidates = [line for line in order_items if line.external_line_id == external_order_item_id]
            if len(candidates) == 1:
                order_item = candidates[0]
        current = existing_items.get(external_item_id)
        sku = resolved.get(str(item_payload.get('seller_sku') or '').strip())
        sku_id = order_item.internal_sku_id if order_item is not None else (sku.id if sku else None)
        # Never replace an established link or override conflicting source evidence.
        if order_item is not None and sku is not None and sku.id != sku_id:
            sku_id = None
        sku_fields = {'internal_sku_id': sku_id} if sku_id and (current is None or current.internal_sku_id is None) else {}
        saved_item, _ = RefundReturnItem.objects.update_or_create(
            refund_return=refund,
            external_return_item_id=external_item_id,
            defaults={
                "sales_order_item": order_item,
                **sku_fields,
                "external_order_item_id": external_order_item_id,
                "platform_product_id": str(item_payload.get("platform_product_id") or ""),
                "platform_variant_id": str(item_payload.get("platform_variant_id") or ""),
                "seller_sku": str(item_payload.get("seller_sku") or ""),
                "item_name_snapshot": str(item_payload.get("item_name_snapshot") or ""),
                "quantity": int(item_payload.get("quantity") or 0),
                "currency": str(item_payload.get("currency") or defaults["currency"]).upper(),
                "refund_amount": _decimal(item_payload.get("refund_amount")),
                **({'source_details': item_payload['amount_observations']}
                   if store.platform.platform_type == 'shopee' and isinstance(item_payload.get('amount_observations'), dict) else {}),
            },
        )
        if sku_fields:
            sku_changes.append({'model': 'RefundReturnItem', 'id': saved_item.id, 'before_internal_sku_id': None,
                                'after_internal_sku_id': sku_id})
    audit_sku_links(source_run, sku_changes)
    refund._sku_link_count = order_links + len(sku_changes)
    if sales_order and isinstance(payload.get('platform_logistics'), dict):
        from apps.integrations.order_field_mapping import timestamp
        from apps.integrations.shopee_logistics import safe_snapshot
        locked_order = SalesOrder.objects.select_for_update().get(pk=sales_order.pk, tenant=tenant)
        details = dict(locked_order.source_details or {})
        snapshots = dict(details.get('platform_return_logistics') or {})
        incoming = safe_snapshot(payload['platform_logistics'])
        previous = snapshots.get(external_return_id) or {}
        incoming_time = timestamp(incoming.get('collected_at_utc'))
        previous_time = timestamp(previous.get('collected_at_utc'))
        if incoming_time and (not previous_time or _utc(incoming_time, 'collected_at_utc') >= _utc(previous_time, 'collected_at_utc')):
            snapshots[external_return_id] = {**incoming, 'source_run_id': source_run.id}
            locked_order.source_details = {**details, 'platform_return_logistics': snapshots}
            locked_order.save(update_fields=['source_details'])
        refund.sales_order = locked_order
    from .aftersales import track_source
    track_source(refund)
    return refund


__all__ = ["create_export_request", "upsert_normalized_order", "upsert_normalized_refund"]
