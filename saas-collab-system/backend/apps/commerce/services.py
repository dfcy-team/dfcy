import hashlib
import json
from datetime import UTC, datetime

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.integrations.models import PlatformChoices, SyncRun
from apps.masterdata.models import WarehouseMaster

from .models import InventorySnapshot


def _canonical_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc(value, field_name):
    parsed = value if isinstance(value, datetime) else parse_datetime(str(value or ""))
    if parsed is None or parsed.tzinfo is None:
        raise ValidationError({field_name: "A timezone-aware timestamp is required."})
    return parsed.astimezone(UTC)


@transaction.atomic
def upsert_inventory_snapshot(*, tenant, payload, source_run):
    if not isinstance(source_run, SyncRun) or source_run.tenant_id != tenant.id:
        raise ValidationError({"source_run": "A same-tenant SyncRun is required."})
    job = source_run.sync_job
    if job.resource_type != "inventory_snapshot":
        raise ValidationError({"source_run": "SyncRun must use the inventory_snapshot resource type."})
    if job.integration_config.platform != PlatformChoices.JIFENG_WMS:
        raise ValidationError({"source_run": "Inventory snapshots require a Jifeng WMS sync run."})

    warehouse_reference = payload.get("warehouse_id") or payload.get("warehouse_code")
    warehouses = WarehouseMaster.objects.filter(tenant=tenant)
    warehouse = (
        warehouses.filter(pk=warehouse_reference).first()
        if str(warehouse_reference).isdigit()
        else warehouses.filter(code=warehouse_reference).first()
    )
    if warehouse is None:
        raise ValidationError({"warehouse_id": "A tenant-owned warehouse is required."})
    site_code = str(payload.get("site_code") or "").upper()
    if site_code != warehouse.country_code.upper():
        raise ValidationError({"site_code": "Site code must match the warehouse country."})
    source_sku = str(payload.get("source_sku") or "").strip()
    if not source_sku:
        raise ValidationError({"source_sku": "Source SKU is required."})
    snapshot_at = _utc(payload.get("snapshot_at_utc"), "snapshot_at_utc")
    lookup = {
        "tenant": tenant,
        "site_code": site_code,
        "warehouse": warehouse,
        "source_sku": source_sku,
        "snapshot_at_utc": snapshot_at,
    }
    snapshot, _created = InventorySnapshot.objects.update_or_create(
        **lookup,
        defaults={
            "source_run": source_run,
            "platform_product_id": str(payload.get("platform_product_id") or ""),
            "platform_variant_id": str(payload.get("platform_variant_id") or ""),
            "seller_sku": str(payload.get("seller_sku") or ""),
            "on_hand_qty": int(payload.get("on_hand_qty") or 0),
            "available_qty": int(payload.get("available_qty") or 0),
            "reserved_qty": int(payload.get("reserved_qty") or 0),
            "in_transit_qty": int(payload.get("in_transit_qty") or 0),
            "pending_putaway_qty": int(payload.get("pending_putaway_qty") or 0),
            "defective_qty": int(payload.get("defective_qty") or 0),
            "payload_hash": str(payload.get("payload_hash") or _canonical_hash(payload)),
        },
    )
    return snapshot
