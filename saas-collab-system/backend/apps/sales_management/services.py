import hashlib
import json
from datetime import date

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog

from .models import SalesExportRequest, SalesOrder, SalesOrderLine, SyncRerunRequest, SyncSource


ORDER_UPDATE_FIELDS = {
    "system_order_no",
    "region",
    "order_status",
    "fulfillment_status",
    "refund_status",
    "currency",
    "gross_amount",
    "net_amount",
    "discount_amount",
    "tax_amount",
    "shipping_amount",
    "buyer_region",
    "ordered_at",
    "source_updated_at",
}
EXPORT_DIMENSION_FIELDS = {"store_id", "store_ids", "platform", "platforms", "region", "regions"}
EXPORT_COMMON_FILTER_FIELDS = EXPORT_DIMENSION_FIELDS | {"date_from", "date_to", "currency"}
EXPORT_FILTER_FIELDS = {
    "orders": EXPORT_COMMON_FILTER_FIELDS | {"order_no", "order_status", "fulfillment_status", "refund_status", "sku"},
    "order_lines": EXPORT_COMMON_FILTER_FIELDS | {"order_no", "spu", "sku"},
    "returns": EXPORT_COMMON_FILTER_FIELDS | {"order_no", "return_type", "status", "reason", "sku"},
    "store_sales": EXPORT_COMMON_FILTER_FIELDS,
    "sku_sales": EXPORT_COMMON_FILTER_FIELDS | {"spu", "sku", "category", "inventory_risk"},
}
SENSITIVE_FILTER_KEY_PARTS = ("authorization", "cookie", "credential", "password", "secret", "session", "token")
RERUNNABLE_SYNC_STATUSES = {"failed", "partial"}
EXPORT_REQUEST_KEY_MAX_LENGTH = SalesExportRequest._meta.get_field("request_key").max_length
SYNC_RERUN_REQUEST_KEY_MAX_LENGTH = SyncRerunRequest._meta.get_field("request_key").max_length
SYNC_RERUN_REASON_MAX_LENGTH = SyncRerunRequest._meta.get_field("reason").max_length


def _stable_value(value):
    if isinstance(value, dict):
        return {key: _stable_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_stable_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return value


def _request_fingerprint(payload):
    canonical = json.dumps(_stable_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _reject_idempotency_conflict(existing_fingerprint, candidate_fingerprint):
    if existing_fingerprint != candidate_fingerprint:
        raise ValidationError("Idempotency-Key cannot be reused with a different actor, payload, or data scope.")


def _contains_sensitive_filter_key(value):
    if isinstance(value, dict):
        return any(
            any(part in str(key).lower() for part in SENSITIVE_FILTER_KEY_PARTS)
            or _contains_sensitive_filter_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_filter_key(item) for item in value)
    return False


def validate_export_filters(export_type, filters):
    if not isinstance(filters, dict):
        raise ValidationError("Export filters must be an object.")
    if _contains_sensitive_filter_key(filters):
        raise ValidationError("Sensitive fields are not allowed in export filters.")
    allowed_fields = EXPORT_FILTER_FIELDS.get(export_type, set())
    unknown_fields = sorted(set(filters) - allowed_fields)
    if unknown_fields:
        raise ValidationError({"filters": [f"Unsupported export filter fields: {', '.join(unknown_fields)}"]})
    normalized = {}
    for key, value in filters.items():
        if value in (None, "", []):
            continue
        if key in {"store_ids", "platforms", "regions"}:
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValidationError({"filters": [f"{key} must be a non-empty list of strings."]})
            normalized[key] = [item.strip() for item in value]
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValidationError({"filters": [f"{key} must be a string."]})
        value = value.strip()
        if key in {"date_from", "date_to"}:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError({"filters": [f"{key} must use YYYY-MM-DD format."]}) from exc
        normalized[key] = value
    return normalized


def validate_sync_rerun_request(request_key, reason):
    if not isinstance(request_key, str) or not request_key.strip():
        raise ValidationError("Idempotency-Key is required.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("A rerun reason is required.")
    request_key = request_key.strip()
    reason = reason.strip()
    if len(request_key) > SYNC_RERUN_REQUEST_KEY_MAX_LENGTH:
        raise ValidationError(f"Idempotency-Key must be at most {SYNC_RERUN_REQUEST_KEY_MAX_LENGTH} characters.")
    if len(reason) > SYNC_RERUN_REASON_MAX_LENGTH:
        raise ValidationError(f"Rerun reason must be at most {SYNC_RERUN_REASON_MAX_LENGTH} characters.")
    return request_key, reason


def validate_export_request_key(request_key):
    if not isinstance(request_key, str) or not request_key.strip():
        raise ValidationError("Idempotency-Key is required.")
    request_key = request_key.strip()
    if len(request_key) > EXPORT_REQUEST_KEY_MAX_LENGTH:
        raise ValidationError(f"Idempotency-Key must be at most {EXPORT_REQUEST_KEY_MAX_LENGTH} characters.")
    return request_key


@transaction.atomic
def upsert_normalized_order(*, tenant, payload, source_batch):
    lookup = {
        "tenant": tenant,
        "platform": payload["platform"],
        "store_id": payload["store_id"],
        "source_order_id": payload["source_order_id"],
    }
    defaults = {key: value for key, value in payload.items() if key in ORDER_UPDATE_FIELDS}
    defaults["source_batch"] = source_batch
    order, _ = SalesOrder.objects.update_or_create(**lookup, defaults=defaults)
    for index, line_payload in enumerate(payload.get("lines") or [], start=1):
        line_defaults = dict(line_payload)
        source_line_id = str(line_defaults.pop("source_line_id", index))
        line = SalesOrderLine(
            tenant=tenant,
            order=order,
            source_line_id=source_line_id,
            **line_defaults,
        )
        line.clean()
        SalesOrderLine.objects.update_or_create(
            tenant=tenant,
            order=order,
            source_line_id=source_line_id,
            defaults=line_defaults,
        )
    return order


@transaction.atomic
def create_export_request(*, user, request_key, export_type, filters, data_scope):
    request_key = validate_export_request_key(request_key)
    filters = validate_export_filters(export_type, filters)
    fingerprint = _request_fingerprint(
        {
            "actor_id": user.pk,
            "export_type": export_type,
            "filters": filters,
            "data_scope": data_scope,
        }
    )
    export, created = SalesExportRequest.objects.get_or_create(
        tenant=user.tenant,
        requested_by=user,
        request_key=request_key,
        defaults={
            "request_fingerprint": fingerprint,
            "export_type": export_type,
            "filters": filters,
            "data_scope": data_scope,
        },
    )
    if not created:
        _reject_idempotency_conflict(export.request_fingerprint, fingerprint)
    if created:
        OperationLog.objects.create(
            tenant=user.tenant,
            user=user,
            module="sales_management",
            action="export.requested",
            object_type="SalesExportRequest",
            object_id=str(export.id),
            after_data={"export_type": export_type, "filters": filters, "data_scope": data_scope},
        )
    return export, created


@transaction.atomic
def create_sync_rerun_request(*, user, source, request_key, reason, data_scope):
    request_key, reason = validate_sync_rerun_request(request_key, reason)
    fingerprint = _request_fingerprint(
        {
            "actor_id": user.pk,
            "sync_source_id": source.pk,
            "reason": reason,
            "data_scope": data_scope,
        }
    )
    lookup = {
        "tenant": user.tenant,
        "requested_by": user,
        "request_key": request_key,
    }
    rerun = SyncRerunRequest.objects.filter(**lookup).first()
    if rerun:
        _reject_idempotency_conflict(rerun.request_fingerprint, fingerprint)
        return rerun, False

    type(user).objects.select_for_update().only("pk").get(pk=user.pk)
    rerun = SyncRerunRequest.objects.select_for_update().filter(**lookup).first()
    if rerun:
        _reject_idempotency_conflict(rerun.request_fingerprint, fingerprint)
        return rerun, False

    locked_source = SyncSource.objects.select_for_update().get(pk=source.pk, tenant=user.tenant)
    if locked_source.run_status not in RERUNNABLE_SYNC_STATUSES:
        raise ValidationError("Only failed or partially successful sync sources can be rerun.")
    rerun = SyncRerunRequest(
        tenant=user.tenant,
        requested_by=user,
        request_key=request_key,
        sync_source=locked_source,
        request_fingerprint=fingerprint,
        reason=reason,
        data_scope=data_scope,
    )
    rerun.full_clean(exclude=["id"])
    rerun.save(force_insert=True)
    OperationLog.objects.create(
        tenant=user.tenant,
        user=user,
        module="sales_management",
        action="sync.rerun_requested",
        object_type="SyncRerunRequest",
        object_id=str(rerun.id),
        after_data={"sync_source_id": locked_source.id, "reason": reason, "status": rerun.status},
    )
    return rerun, True
