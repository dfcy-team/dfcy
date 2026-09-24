import hashlib
import json
from datetime import UTC, datetime

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.integrations.models import IntegrationAuditLog, PlatformChoices, SyncRun
from apps.masterdata.models import WarehouseMaster

from .models import InventorySnapshot
from .inventory_sku_mapping import resolve_inventory_sku, resolve_inventory_skus


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
    config = job.integration_config
    if job.tenant_id != tenant.id or config.tenant_id != tenant.id or config.created_by.tenant_id != tenant.id:
        raise ValidationError({"source_run": "Sync job, configuration and owner must belong to the tenant."})
    if job.resource_type != "inventory_snapshot":
        raise ValidationError({"source_run": "SyncRun must use the inventory_snapshot resource type."})
    if job.integration_config.platform != PlatformChoices.JIFENG_WMS:
        raise ValidationError({"source_run": "Inventory snapshots require a Jifeng WMS sync run."})

    warehouse_reference = payload.get("warehouse_id") or payload.get("warehouse_code")
    # Serialize ingestion for a warehouse so parallel runs cannot create
    # competing initial links for the same source SKU.
    warehouses = WarehouseMaster.objects.select_for_update().filter(tenant=tenant)
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
    if snapshot.internal_sku_id is None:
        sku_id, rule = resolve_inventory_sku(
            tenant=tenant, warehouse=warehouse, source_sku=source_sku, seller_sku=snapshot.seller_sku,
        )
        if sku_id is not None:
            snapshot.internal_sku_id = sku_id
            snapshot.save(update_fields=["internal_sku"])
        if sku_id is not None or _created:
            IntegrationAuditLog.objects.create(
                tenant=tenant, integration_config=config, actor=config.created_by,
                action="inventory_auto_sku_link",
                result=IntegrationAuditLog.Result.SUCCESS if sku_id is not None else IntegrationAuditLog.Result.BLOCKED,
                masked_detail={
                    "automatic": True, "actor_basis": "configuration_owner", "rule": rule,
                    "snapshot_id": snapshot.id, "warehouse_id": warehouse.id, "source_run_id": source_run.id,
                    "before_internal_sku_id": None, "after_internal_sku_id": sku_id,
                },
            )
    return snapshot


@transaction.atomic
def bulk_upsert_inventory_snapshots(*, tenant, payloads, source_run):
    payloads = list(payloads)
    if not payloads:
        return []
    if not isinstance(source_run, SyncRun) or source_run.tenant_id != tenant.id:
        raise ValidationError({"source_run": "A same-tenant SyncRun is required."})
    job = source_run.sync_job
    config = job.integration_config
    if job.tenant_id != tenant.id or config.tenant_id != tenant.id or config.created_by.tenant_id != tenant.id:
        raise ValidationError({"source_run": "Sync job, configuration and owner must belong to the tenant."})
    if job.resource_type != "inventory_snapshot" or config.platform != PlatformChoices.JIFENG_WMS:
        raise ValidationError({"source_run": "SyncRun must use the Jifeng WMS inventory_snapshot resource type."})

    warehouse_references = {
        str(payload.get("warehouse_id") or payload.get("warehouse_code") or "")
        for payload in payloads
    }
    if len(warehouse_references) != 1:
        raise ValidationError({"warehouse_id": "One inventory page must belong to one warehouse."})
    warehouse_reference = next(iter(warehouse_references))
    warehouses = WarehouseMaster.objects.select_for_update().filter(tenant=tenant)
    warehouse = (
        warehouses.filter(pk=warehouse_reference).first()
        if warehouse_reference.isdigit()
        else warehouses.filter(code=warehouse_reference).first()
    )
    if warehouse is None:
        raise ValidationError({"warehouse_id": "A tenant-owned warehouse is required."})

    prepared = []
    for payload in payloads:
        site_code = str(payload.get("site_code") or "").upper()
        if site_code != warehouse.country_code.upper():
            raise ValidationError({"site_code": "Site code must match the warehouse country."})
        source_sku = str(payload.get("source_sku") or "").strip()
        if not source_sku:
            raise ValidationError({"source_sku": "Source SKU is required."})
        snapshot_at = _utc(payload.get("snapshot_at_utc"), "snapshot_at_utc")
        prepared.append((payload, site_code, source_sku, snapshot_at))

    keys = [(site, source_sku, snapshot_at) for _payload, site, source_sku, snapshot_at in prepared]
    if len(keys) != len(set(keys)):
        results = []
        for payload, site_code, source_sku, snapshot_at in prepared:
            existing = InventorySnapshot.objects.filter(
                tenant=tenant, warehouse=warehouse, site_code=site_code,
                source_sku=source_sku, snapshot_at_utc=snapshot_at,
            ).first()
            before_hash = existing.payload_hash if existing else ""
            before_sku = existing.internal_sku_id if existing else None
            saved = upsert_inventory_snapshot(tenant=tenant, payload=payload, source_run=source_run)
            unchanged = existing is not None and before_hash == saved.payload_hash and before_sku == saved.internal_sku_id
            results.append({"snapshot": saved, "action": "created" if existing is None else "skipped" if unchanged else "updated"})
        return results

    existing_by_key = {
        (row.site_code, row.source_sku, row.snapshot_at_utc): row
        for row in InventorySnapshot.objects.select_for_update().filter(
            tenant=tenant,
            warehouse=warehouse,
            site_code__in={key[0] for key in keys},
            source_sku__in={key[1] for key in keys},
            snapshot_at_utc__in={key[2] for key in keys},
        )
    }
    resolutions = resolve_inventory_skus(
        tenant=tenant,
        warehouse=warehouse,
        sku_pairs=[
            (source_sku, str(payload.get("seller_sku") or ""))
            for payload, _site, source_sku, _snapshot_at in prepared
        ],
    )
    fields = (
        "source_run", "platform_product_id", "platform_variant_id", "seller_sku",
        "on_hand_qty", "available_qty", "reserved_qty", "in_transit_qty",
        "pending_putaway_qty", "defective_qty", "payload_hash",
    )
    result_by_key = {}
    new_rows = []
    audit_rules = {}
    for payload, site_code, source_sku, snapshot_at in prepared:
        key = (site_code, source_sku, snapshot_at)
        seller_sku = str(payload.get("seller_sku") or "")
        sku_id, rule = resolutions[(source_sku, seller_sku)]
        values = {
            "source_run": source_run,
            "platform_product_id": str(payload.get("platform_product_id") or ""),
            "platform_variant_id": str(payload.get("platform_variant_id") or ""),
            "seller_sku": seller_sku,
            "on_hand_qty": int(payload.get("on_hand_qty") or 0),
            "available_qty": int(payload.get("available_qty") or 0),
            "reserved_qty": int(payload.get("reserved_qty") or 0),
            "in_transit_qty": int(payload.get("in_transit_qty") or 0),
            "pending_putaway_qty": int(payload.get("pending_putaway_qty") or 0),
            "defective_qty": int(payload.get("defective_qty") or 0),
            "payload_hash": str(payload.get("payload_hash") or _canonical_hash(payload)),
        }
        snapshot = existing_by_key.get(key)
        if snapshot is None:
            snapshot = InventorySnapshot(
                tenant=tenant, site_code=site_code, warehouse=warehouse,
                source_sku=source_sku, snapshot_at_utc=snapshot_at,
                internal_sku_id=sku_id, **values,
            )
            new_rows.append(snapshot)
            audit_rules[key] = (sku_id, rule)
            continue
        before_hash = snapshot.payload_hash
        before_sku = snapshot.internal_sku_id
        for field_name, value in values.items():
            setattr(snapshot, field_name, value)
        if snapshot.internal_sku_id is None and sku_id is not None:
            snapshot.internal_sku_id = sku_id
            audit_rules[key] = (sku_id, rule)
        unchanged = before_hash == snapshot.payload_hash and before_sku == snapshot.internal_sku_id
        if not unchanged:
            snapshot.save(update_fields=[*fields, "internal_sku"])
        result_by_key[key] = {"snapshot": snapshot, "action": "skipped" if unchanged else "updated"}

    if new_rows:
        InventorySnapshot.objects.bulk_create(new_rows, batch_size=300)
        created_by_key = {
            (row.site_code, row.source_sku, row.snapshot_at_utc): row
            for row in InventorySnapshot.objects.filter(
                tenant=tenant, warehouse=warehouse,
                source_sku__in={row.source_sku for row in new_rows},
                snapshot_at_utc__in={row.snapshot_at_utc for row in new_rows},
            )
        }
        for key in audit_rules:
            if key in created_by_key:
                result_by_key[key] = {"snapshot": created_by_key[key], "action": "created"}

    audits = []
    for key, (sku_id, rule) in audit_rules.items():
        snapshot = result_by_key[key]["snapshot"]
        audits.append(IntegrationAuditLog(
            tenant=tenant,
            integration_config=config,
            actor=config.created_by,
            action="inventory_auto_sku_link",
            result=IntegrationAuditLog.Result.SUCCESS if sku_id is not None else IntegrationAuditLog.Result.BLOCKED,
            masked_detail={
                "automatic": True, "actor_basis": "configuration_owner", "rule": rule,
                "snapshot_id": snapshot.id, "warehouse_id": warehouse.id, "source_run_id": source_run.id,
                "before_internal_sku_id": None, "after_internal_sku_id": sku_id,
            },
        ))
    if audits:
        IntegrationAuditLog.objects.bulk_create(audits, batch_size=300)
    return [result_by_key[key] for key in keys]
