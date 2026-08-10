import hashlib
import json
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.integrations.models import MarketplaceProductMapping, MarketplaceStoreMapping

from .models import (
    MarketplaceImportBatch,
    MarketplaceImportCursor,
    MarketplaceInventorySnapshot,
    MarketplaceOrder,
    MarketplaceRefund,
    import_service_write,
)


class ImportStateConflict(StateConflict):
    error_code = "MARKETPLACE_IMPORT_CONFLICT"


class ImportRuleViolation(BusinessRuleViolation):
    error_code = "MARKETPLACE_IMPORT_REJECTED"


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _digest(value):
    encoded = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _masked_key_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _batch_payload(payload):
    return {key: value for key, value in payload.items() if key != "idempotency_key"}


def _existing_batch(*, tenant, store_mapping, resource_type, key_hash, payload_hash, allow_retry):
    batch = MarketplaceImportBatch.objects.filter(
        tenant=tenant,
        store_mapping=store_mapping,
        resource_type=resource_type,
        idempotency_key_hash=key_hash,
    ).first()
    if not batch:
        return None
    if batch.payload_hash != payload_hash:
        raise ImportStateConflict("Idempotency key was already used for a different normalized payload.")
    if batch.status == MarketplaceImportBatch.Status.COMPLETED:
        return batch
    if batch.status == MarketplaceImportBatch.Status.FAILED and allow_retry:
        return batch
    raise ImportStateConflict("Import batch is not eligible for this operation.")


def _create_batch(*, tenant, actor, store_mapping, payload, key_hash, payload_hash):
    with import_service_write():
        return MarketplaceImportBatch.objects.create(
            tenant=tenant,
            store_mapping=store_mapping,
            platform=store_mapping.platform,
            resource_type=payload["resource_type"],
            import_mode=payload["import_mode"],
            source_mode=payload["source_mode"],
            contract_version=payload["contract_version"],
            idempotency_key_hash=key_hash,
            payload_hash=payload_hash,
            cursor_before=payload["cursor_before"],
            cursor_after=payload["cursor_after"],
            watermark_after=payload["watermark_after"],
            received_count=len(payload[payload["resource_type"]]),
            created_by=actor,
        )


def _validate_cursor(cursor, payload):
    if payload["import_mode"] == MarketplaceImportBatch.Mode.INITIAL:
        if payload["cursor_before"]:
            raise ImportStateConflict("Initial imports require an empty cursor_before.")
        if cursor.version or cursor.cursor or cursor.watermark:
            raise ImportStateConflict("Initial import has already completed for this store and resource.")
    elif payload["cursor_before"] != cursor.cursor:
        raise ImportStateConflict("cursor_before does not match the committed cursor.")
    if cursor.watermark and payload["watermark_after"] < cursor.watermark:
        raise ImportStateConflict("watermark_after cannot move backwards.")


def _order_fields(record):
    return {
        "platform_order_id": record["platform_order_id"],
        "status": record["status"],
        "currency": record["currency"],
        "total_amount": record["total_amount"],
        "ordered_at": record["ordered_at"],
        "platform_updated_at": record["platform_updated_at"],
        "cancelled_at": record.get("cancelled_at"),
        "line_items": _json_value(record["line_items"]),
    }


def _upsert_order(*, tenant, store_mapping, batch, record):
    fields = _order_fields(record)
    fingerprint = _digest(fields)
    order = MarketplaceOrder.objects.select_for_update().filter(
        tenant=tenant,
        store_mapping=store_mapping,
        platform_order_id=record["platform_order_id"],
    ).first()
    if order is None:
        with import_service_write():
            order = MarketplaceOrder.objects.create(
                tenant=tenant,
                store_mapping=store_mapping,
                fingerprint=fingerprint,
                last_batch=batch,
                **fields,
            )
        result = "created"
    elif record["platform_updated_at"] < order.platform_updated_at:
        result = "skipped"
    elif record["platform_updated_at"] == order.platform_updated_at:
        if fingerprint != order.fingerprint:
            raise ImportStateConflict("An order event reused a timestamp with different content.")
        result = "skipped"
    elif order.status in {MarketplaceOrder.Status.COMPLETED, MarketplaceOrder.Status.CANCELLED}:
        raise ImportStateConflict("A terminal order cannot transition to another state.")
    elif fingerprint == order.fingerprint:
        result = "skipped"
    else:
        for name, value in fields.items():
            setattr(order, name, value)
        order.fingerprint = fingerprint
        order.last_batch = batch
        with import_service_write():
            order.save()
        result = "updated"
    for refund in record.get("refunds", []):
        _upsert_refund(tenant=tenant, order=order, batch=batch, record=refund)
    return result


def _upsert_refund(*, tenant, order, batch, record):
    fields = {
        "status": record["status"],
        "currency": record["currency"],
        "amount": record["amount"],
        "reason_code": record.get("reason_code", ""),
        "platform_updated_at": record["platform_updated_at"],
    }
    fingerprint = _digest(fields)
    refund = MarketplaceRefund.objects.select_for_update().filter(
        tenant=tenant,
        order=order,
        platform_refund_id=record["platform_refund_id"],
    ).first()
    if refund is None:
        with import_service_write():
            MarketplaceRefund.objects.create(
                tenant=tenant,
                order=order,
                platform_refund_id=record["platform_refund_id"],
                fingerprint=fingerprint,
                last_batch=batch,
                **fields,
            )
        return
    if record["platform_updated_at"] < refund.platform_updated_at:
        return
    if record["platform_updated_at"] == refund.platform_updated_at:
        if fingerprint != refund.fingerprint:
            raise ImportStateConflict("A refund event reused a timestamp with different content.")
        return
    if refund.status in {
        MarketplaceRefund.Status.REJECTED,
        MarketplaceRefund.Status.COMPLETED,
        MarketplaceRefund.Status.CANCELLED,
    }:
        raise ImportStateConflict("A terminal refund cannot transition to another state.")
    for name, value in fields.items():
        setattr(refund, name, value)
    refund.fingerprint = fingerprint
    refund.last_batch = batch
    with import_service_write():
        refund.save()


def _insert_inventory(*, tenant, store_mapping, batch, record):
    fields = {
        "platform_variant_id": record["platform_variant_id"],
        "platform_sku": record.get("platform_sku", ""),
        "on_hand": record["on_hand"],
        "reserved": record["reserved"],
        "available": record["available"],
        "incoming": record["incoming"],
        "observed_at": record["observed_at"],
    }
    fingerprint = _digest(fields)
    latest = MarketplaceInventorySnapshot.objects.select_for_update().filter(
        tenant=tenant,
        store_mapping=store_mapping,
        platform_variant_id=record["platform_variant_id"],
    ).order_by("-observed_at", "-id").first()
    if latest and record["observed_at"] < latest.observed_at:
        return "skipped"
    if latest and record["observed_at"] == latest.observed_at:
        if fingerprint != latest.fingerprint:
            raise ImportStateConflict("An inventory observation reused a timestamp with different content.")
        return "skipped"
    product_mapping = MarketplaceProductMapping.objects.filter(
        tenant=tenant,
        store_mapping=store_mapping,
        platform_variant_id=record["platform_variant_id"],
        status=MarketplaceProductMapping.Status.MAPPED,
    ).first()
    with import_service_write():
        MarketplaceInventorySnapshot.objects.create(
            tenant=tenant,
            store_mapping=store_mapping,
            product_mapping=product_mapping,
            mapping_status=(
                MarketplaceInventorySnapshot.MappingStatus.MAPPED
                if product_mapping
                else MarketplaceInventorySnapshot.MappingStatus.UNMAPPED
            ),
            fingerprint=fingerprint,
            last_batch=batch,
            **fields,
        )
    return "created"


def _execute_batch(batch, payload):
    with transaction.atomic():
        batch = MarketplaceImportBatch.objects.select_for_update().get(pk=batch.pk)
        with import_service_write():
            cursor, _ = MarketplaceImportCursor.objects.select_for_update().get_or_create(
                tenant=batch.tenant,
                store_mapping=batch.store_mapping,
                resource_type=batch.resource_type,
            )
        _validate_cursor(cursor, payload)
        batch.watermark_before = cursor.watermark
        counts = {"created": 0, "updated": 0, "skipped": 0}
        records = payload[payload["resource_type"]]
        for record in records:
            if payload["resource_type"] == "orders":
                result = _upsert_order(
                    tenant=batch.tenant,
                    store_mapping=batch.store_mapping,
                    batch=batch,
                    record=record,
                )
            else:
                result = _insert_inventory(
                    tenant=batch.tenant,
                    store_mapping=batch.store_mapping,
                    batch=batch,
                    record=record,
                )
            counts[result] += 1
        cursor.cursor = payload["cursor_after"]
        cursor.watermark = payload["watermark_after"]
        cursor.version += 1
        cursor.last_batch = batch
        batch.status = MarketplaceImportBatch.Status.COMPLETED
        batch.created_count = counts["created"]
        batch.updated_count = counts["updated"]
        batch.skipped_count = counts["skipped"]
        batch.completed_at = timezone.now()
        batch.controlled_error_code = ""
        with import_service_write():
            cursor.save()
            batch.save()
        return batch


def import_normalized_batch(*, tenant, actor, store_mapping, payload, allow_retry=False):
    if store_mapping.tenant_id != tenant.id or store_mapping.status != MarketplaceStoreMapping.Status.ACTIVE:
        raise ImportRuleViolation("An active store mapping in the current tenant is required.")
    key_hash = _masked_key_hash(payload["idempotency_key"])
    payload_hash = _digest(_batch_payload(payload))
    existing = _existing_batch(
        tenant=tenant,
        store_mapping=store_mapping,
        resource_type=payload["resource_type"],
        key_hash=key_hash,
        payload_hash=payload_hash,
        allow_retry=allow_retry,
    )
    if existing and existing.status == MarketplaceImportBatch.Status.COMPLETED:
        return existing, True
    if existing:
        batch = existing
        batch.status = MarketplaceImportBatch.Status.PROCESSING
        batch.controlled_error_code = ""
        with import_service_write():
            batch.save()
    else:
        try:
            with transaction.atomic():
                batch = _create_batch(
                    tenant=tenant,
                    actor=actor,
                    store_mapping=store_mapping,
                    payload=payload,
                    key_hash=key_hash,
                    payload_hash=payload_hash,
                )
        except IntegrityError:
            concurrent = _existing_batch(
                tenant=tenant,
                store_mapping=store_mapping,
                resource_type=payload["resource_type"],
                key_hash=key_hash,
                payload_hash=payload_hash,
                allow_retry=False,
            )
            if concurrent and concurrent.status == MarketplaceImportBatch.Status.COMPLETED:
                return concurrent, True
            raise ImportStateConflict("A concurrent request already owns this idempotency key.")
    try:
        return _execute_batch(batch, payload), False
    except (ImportStateConflict, ImportRuleViolation, DjangoValidationError) as exc:
        with import_service_write():
            MarketplaceImportBatch.objects.filter(pk=batch.pk).update(
                status=MarketplaceImportBatch.Status.FAILED,
                controlled_error_code=getattr(exc, "error_code", "MARKETPLACE_IMPORT_REJECTED"),
                completed_at=timezone.now(),
            )
        raise
    except Exception as exc:
        with import_service_write():
            MarketplaceImportBatch.objects.filter(pk=batch.pk).update(
                status=MarketplaceImportBatch.Status.FAILED,
                controlled_error_code="MARKETPLACE_IMPORT_INTERNAL_FAILURE",
                completed_at=timezone.now(),
            )
        raise ImportRuleViolation("The import failed without advancing its cursor.") from exc
