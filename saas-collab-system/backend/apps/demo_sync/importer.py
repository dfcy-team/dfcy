"""Validated, idempotent import of demo snapshots into native local models."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import IntegrityError, connections, transaction
from django.utils.dateparse import parse_date, parse_datetime

from .pipeline import FIELDS, ID_ALIASES, RESOURCES, SCHEMA_VERSION, SnapshotError, _validate_relations


class SnapshotImportError(ValueError):
    """The bundle or local import target is not eligible for import."""


MODEL_MAP = {
    "platforms": ("apps.masterdata.models", "PlatformMaster"),
    "country_sites": ("apps.masterdata.models", "CountrySiteMaster"),
    "stores": ("apps.masterdata.models", "StoreMaster"),
    "warehouses": ("apps.masterdata.models", "WarehouseMaster"),
    "product_categories": ("apps.products.models", "ProductCategory"),
    "products": ("apps.products.models", "ProductSPU"),
    "product_details": ("apps.products.models", "ProductSKU"),
    "sales_orders": ("apps.commerce.models", "SalesOrder"),
    "sales_order_items": ("apps.commerce.models", "SalesOrderItem"),
    "inventory_snapshots": ("apps.commerce.models", "InventorySnapshot"),
}
ID_FIELDS = {
    "platforms": ("id",), "country_sites": ("id",), "stores": ("id",),
    "warehouses": ("id",), "product_categories": ("id",),
    "products": ("id",), "product_details": ("id",),
    "sales_orders": ("id",), "sales_order_items": ("id",),
    "inventory_snapshots": ("id",),
}
DECIMAL_FIELDS = {
    "package_weight", "package_volume", "purchase_price", "package_length_cm",
    "package_width_cm", "package_height_cm", "cny_exchange_rate", "subtotal_amount",
    "seller_discount_amount", "platform_discount_amount", "shipping_amount", "tax_amount",
    "order_total_amount", "original_unit_price", "sale_unit_price", "discount_amount",
    "line_total_amount",
}
DATE_FIELDS = {"first_sale_date", "business_date", "exchange_rate_date"}
DATETIME_FIELDS = {
    "created_at_utc", "updated_at_utc", "paid_at_utc", "delivered_at_utc",
    "cancelled_at_utc", "completed_at_utc", "snapshot_at_utc",
}
REQUIRED_FIELDS = {
    "platforms": ("code", "name", "platform_type"),
    "country_sites": ("code", "name", "country_code"),
    "stores": ("code", "name", "platform_id", "country_code", "currency"),
    "warehouses": ("code", "name", "country_code", "warehouse_type"),
    "product_categories": ("level", "code", "name"),
    "products": ("spu_code", "product_name"),
    "product_details": ("spu_id", "sku_code"),
    "sales_orders": ("platform_id", "store_id", "external_order_id", "raw_status", "normalized_status",
                     "created_at_utc", "updated_at_utc", "business_date", "currency", "subtotal_amount",
                     "seller_discount_amount", "platform_discount_amount", "shipping_amount", "tax_amount",
                     "order_total_amount"),
    "sales_order_items": ("sales_order_id", "external_line_id", "platform_product_id", "quantity",
                          "original_unit_price", "sale_unit_price", "discount_amount", "tax_amount",
                          "line_total_amount", "currency"),
    "inventory_snapshots": ("site_code", "warehouse_id", "source_sku", "snapshot_at_utc"),
}


def _model(resource: str):
    from django.utils.module_loading import import_string
    module, name = MODEL_MAP[resource]
    return import_string(f"{module}.{name}")


def _database_allowed() -> None:
    if not getattr(settings, "DEMO_DATA_SYNC_IMPORT_ENABLED", False):
        raise SnapshotImportError("demo snapshot import is disabled")
    if getattr(settings, "LIVE_PLATFORM_SECURITY_APPROVED", False) or getattr(settings, "LIVE_READONLY_SYNC_ENABLED", False):
        raise SnapshotImportError("live platform gates must remain disabled during demo import")
    name = str(connections["default"].settings_dict.get("NAME") or "")
    if not (name.startswith("saas_collab_demo_") or getattr(settings, "DEMO_DATA_SYNC_TEST_OVERRIDE", False)):
        raise SnapshotImportError("import target must use a saas_collab_demo_ database or explicit test override")


def _read_bundle(bundle_dir: str | Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], str]:
    root = Path(bundle_dir)
    manifest_path = root / "manifest.json"
    if any(path.is_symlink() for path in (root, *root.parents, manifest_path)):
        raise SnapshotImportError("snapshot symlinks are not permitted")
    try:
        if manifest_path.stat().st_size > 1024 * 1024:
            raise SnapshotImportError("manifest exceeds the size limit")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotImportError("manifest.json is missing or invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("deidentified") is not True:
        raise SnapshotImportError("unsupported or non-deidentified snapshot manifest")
    file_entries = manifest.get("files")
    if not isinstance(file_entries, list):
        raise SnapshotImportError("manifest files must be an array")
    entries = {entry.get("resource"): entry for entry in file_entries if isinstance(entry, dict)}
    if len(file_entries) != len(RESOURCES) or len(entries) != len(file_entries) or set(entries) != set(RESOURCES):
        raise SnapshotImportError("manifest must describe every supported resource exactly once")
    records: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for resource in RESOURCES:
        entry = entries[resource]
        name = entry.get("path")
        if not isinstance(name, str) or name != resource + ".jsonl":
            raise SnapshotImportError("manifest contains an unsafe resource path")
        path = root / name
        if path.is_symlink():
            raise SnapshotImportError("snapshot symlinks are not permitted")
        digest = hashlib.sha256()
        rows = []
        try:
            if path.stat().st_size > 128 * 1024 * 1024:
                raise SnapshotImportError("resource exceeds the file size limit")
            with path.open("rb") as handle:
                for line in handle:
                    if len(line) > 1024 * 1024:
                        raise SnapshotImportError("record exceeds the size limit")
                    digest.update(line)
                    if not line.endswith(b"\n"):
                        raise SnapshotImportError(f"{resource} has an incomplete JSONL line")
                    row = json.loads(line)
                    if not isinstance(row, dict) or not row.get("id"):
                        raise SnapshotImportError(f"{resource} contains an invalid record")
                    rows.append(row)
                    if len(rows) > 100_000:
                        raise SnapshotImportError(f"{resource} exceeds the row limit")
        except SnapshotImportError:
            raise
        except (OSError, ValueError) as exc:
            raise SnapshotImportError(f"{resource} file is missing or invalid") from exc
        if digest.hexdigest() != entry.get("sha256") or len(rows) != entry.get("count"):
            raise SnapshotImportError(f"{resource} checksum or row count does not match manifest")
        if len({_source_id(row) for row in rows}) != len(rows):
            raise SnapshotImportError(f"{resource} contains duplicate source IDs")
        allowed = FIELDS[resource]
        if any(set(row) - allowed for row in rows):
            raise SnapshotImportError(f"{resource} contains fields outside the import whitelist")
        if any(any(row.get(field) in (None, "") for field in REQUIRED_FIELDS[resource]) for row in rows):
            raise SnapshotImportError(f"{resource} is missing required native-model fields")
        records[resource] = rows
        total += len(rows)
        if total > 250_000:
            raise SnapshotImportError("snapshot exceeds total row limit")
    normalized = {resource: [dict(row) for row in rows] for resource, rows in records.items()}
    for resource, aliases in ID_ALIASES.items():
        for row in normalized[resource]:
            for source, target in aliases.items():
                if target not in row and source in row:
                    row[target] = row[source]
                row.pop(source, None)
    try:
        _validate_relations(normalized)
    except SnapshotError as exc:
        raise SnapshotImportError("snapshot contains missing or out-of-scope relationships") from exc
    return manifest, records, hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _source_id(row: dict[str, Any]) -> str:
    value = row.get("id")
    result = str(value) if value is not None else ""
    if not result or len(result) > 64:
        raise SnapshotImportError("source IDs must contain 1 to 64 characters")
    return result


def _value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in DECIMAL_FIELDS:
        result = Decimal(str(value))
        if not result.is_finite():
            raise SnapshotImportError("non-finite decimal values are not permitted")
        return result
    if field in DATE_FIELDS:
        return value if isinstance(value, date) else parse_date(str(value))
    if field in DATETIME_FIELDS:
        parsed = value if isinstance(value, datetime) else parse_datetime(str(value))
        if parsed is None:
            raise SnapshotImportError(f"invalid datetime in {field}")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return value


def _fields(model: Any) -> set[str]:
    return {name for field in model._meta.concrete_fields for name in (field.name, field.attname)}


def _category_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return categories in parent-first order, rejecting cycles defensively."""
    by_id = {_source_id(row): row for row in rows}
    ordered: list[dict[str, Any]] = []
    state: dict[str, int] = {}

    def visit(source_id: str) -> None:
        status = state.get(source_id, 0)
        if status == 1:
            raise SnapshotImportError("product_categories contains a parent cycle")
        if status == 2:
            return
        state[source_id] = 1
        parent_id = by_id[source_id].get("parent_id")
        parent_key = str(parent_id) if parent_id not in (None, "") else None
        if parent_key in by_id:
            visit(parent_key)
        state[source_id] = 2
        ordered.append(by_id[source_id])

    for source_id in by_id:
        visit(source_id)
    return ordered


def _create_or_update(tenant_id: int, resource: str, row: dict[str, Any], values: dict[str, Any], actor_id: int,
                      maps: dict[str, dict[str, Any]]) -> tuple[Any, bool]:
    from .models import SnapshotIdentity
    model = _model(resource)
    source_id = _source_id(row)
    identity = SnapshotIdentity.objects.filter(tenant_id=tenant_id, resource=resource, source_id=source_id).first()
    created = identity is None
    if identity:
        obj = model.objects.filter(pk=identity.target_id, tenant_id=tenant_id).first()
        if obj is None:
            raise SnapshotImportError(f"{resource} identity points to a missing or foreign row")
    else:
        obj = model(**({"tenant_id": tenant_id} if "tenant_id" in _fields(model) else {}))
    data = dict(values)
    if resource == "platforms":
        data["tenant_id"] = tenant_id
    if resource == "country_sites":
        # CountrySiteMaster stores a platform string, not a platform FK.
        source_platform = row.get("platform_id")
        platform = maps["platforms"].get(str(source_platform))
        data["platform"] = platform.platform_type if platform else None
    if resource == "stores":
        data["platform_id"] = _required_map(maps, "platforms", row.get("platform_id"), resource)
        # CountrySiteMaster is not StoreMaster.platform_site's target model.
        data.pop("platform_site_id", None)
        data.pop("country_site_id", None)
        data.setdefault("platform_site_id", None)
    if resource == "warehouses":
        service_id = row.get("service_platform_id", row.get("platform_id"))
        data["service_platform_id"] = maps["platforms"].get(str(service_id)).pk if maps["platforms"].get(str(service_id)) else None
    if resource == "product_categories":
        data["parent_id"] = maps["product_categories"].get(str(row.get("parent_id"))).pk if row.get("parent_id") and maps["product_categories"].get(str(row.get("parent_id"))) else None
    if resource == "products":
        category_source = row.get("category_node_id", row.get("category_id"))
        data["category_node_id"] = maps["product_categories"].get(str(category_source)).pk if category_source and maps["product_categories"].get(str(category_source)) else None
        data.setdefault("product_name", row.get("product_name") or row.get("name") or "Demo product")
        data.setdefault("spu_code", row.get("spu_code") or f"demo-spu-{source_id}")
    if resource == "product_details":
        spu_source = row.get("spu_id")
        data["spu_id"] = _required_map(maps, "products", spu_source, resource)
        data.setdefault("sku_code", row.get("sku_code") or f"demo-sku-{source_id}")
    if resource == "sales_orders":
        data["platform_id"] = _required_map(maps, "platforms", row.get("platform_id"), resource)
        data["store_id"] = _required_map(maps, "stores", row.get("store_id"), resource)
        data["authorization_id"] = maps["configs"][str(row["platform_id"])].pk
        data["source_run_id"] = maps["runs"][f"sales_order|{row['platform_id']}"].pk
        data.setdefault("raw_status", row.get("normalized_status") or "demo")
        data.setdefault("normalized_status", "pending")
        data.setdefault("status_mapping_version", "demo-snapshot.v1")
        data.setdefault("business_date", row.get("business_date") or str(row.get("created_at_utc", ""))[:10])
        # Snapshot payload hashes are local integrity markers, not source data.
        data["payload_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if resource == "sales_order_items":
        order_source = row.get("sales_order_id", row.get("order_id"))
        data["sales_order_id"] = _required_map(maps, "sales_orders", order_source, resource)
        data["internal_spu_id"] = maps["products"].get(str(row.get("internal_spu_id"))).pk if row.get("internal_spu_id") and maps["products"].get(str(row.get("internal_spu_id"))) else None
        data["internal_sku_id"] = maps["product_details"].get(str(row.get("internal_sku_id"))).pk if row.get("internal_sku_id") and maps["product_details"].get(str(row.get("internal_sku_id"))) else None
        data.setdefault("external_line_id", f"demo-line-{source_id}")
        data.setdefault("platform_product_id", "")
        data.setdefault("quantity", 1)
    if resource == "inventory_snapshots":
        data["warehouse_id"] = _required_map(maps, "warehouses", row.get("warehouse_id"), resource)
        data["internal_sku_id"] = maps["product_details"].get(str(row.get("internal_sku_id"))).pk if row.get("internal_sku_id") and maps["product_details"].get(str(row.get("internal_sku_id"))) else None
        data["source_run_id"] = maps["runs"]["inventory_snapshot"].pk
        data["payload_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        data.setdefault("site_code", row.get("country_code") or "DEMO")
    allowed = _fields(model) - {"id", "created_at", "updated_at", "ingested_at"}
    for field_name, value in data.items():
        if field_name in allowed:
            setattr(obj, field_name, _value(field_name, value))
    # Bind required relations through model descriptors after allowlisted
    # source fields are copied.  The source values are never target PKs.
    if resource == "stores":
        obj.platform = maps["platforms"][str(row["platform_id"])]
        obj.platform_site = None
    elif resource == "warehouses":
        service_id = row.get("service_platform_id", row.get("platform_id"))
        obj.service_platform = maps["platforms"].get(str(service_id))
    elif resource == "product_categories" and row.get("parent_id"):
        obj.parent = maps["product_categories"][str(row["parent_id"])]
    elif resource == "products":
        category_source = row.get("category_node_id", row.get("category_id"))
        obj.category_node = maps["product_categories"].get(str(category_source))
    elif resource == "product_details":
        obj.spu = maps["products"][str(row.get("spu_id"))]
    elif resource == "sales_orders":
        obj.platform = maps["platforms"][str(row.get("platform_id"))]
        obj.store = maps["stores"][str(row.get("store_id"))]
        obj.authorization = maps["configs"][str(row["platform_id"])]
        obj.source_run = maps["runs"][f"sales_order|{row['platform_id']}"]
    elif resource == "sales_order_items":
        obj.sales_order = maps["sales_orders"][str(row.get("sales_order_id", row.get("order_id")))]
    elif resource == "inventory_snapshots":
        obj.warehouse = maps["warehouses"][str(row.get("warehouse_id"))]
        obj.source_run = maps["runs"]["inventory_snapshot"]
    # Don't attach source IDs as target PKs. Only SnapshotIdentity controls the
    # mapping, so normal local IDs remain the database's responsibility.
    try:
        obj.save()
    except (IntegrityError, ValueError, TypeError) as exc:
        raise SnapshotImportError(f"{resource} record violates native model constraints") from exc
    if identity is None:
        SnapshotIdentity.objects.create(tenant_id=tenant_id, resource=resource, source_id=source_id, target_id=obj.pk)
    maps[resource][source_id] = obj
    return obj, created


def _required_map(maps: dict[str, dict[str, Any]], resource: str, source_id: Any, owner: str) -> int:
    obj = maps[resource].get(str(source_id))
    if obj is None:
        raise SnapshotImportError(f"{owner} refers to an unmapped {resource} record")
    return obj.pk


def _prepare_configs_and_runs(tenant_id: int, actor_id: int, records: dict[str, list[dict[str, Any]]],
                              manifest_digest: str, maps: dict[str, dict[str, Any]]) -> None:
    from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
    for source_id, obj in maps["platforms"].items() if records["sales_orders"] else ():
        account_alias = f"demo-snapshot-{obj.platform_type}-{manifest_digest[:8]}"[:120]
        config, _ = PlatformIntegrationConfig.objects.get_or_create(
            tenant_id=tenant_id, platform=obj.platform_type, account_alias=account_alias,
            environment=PlatformIntegrationConfig.Environment.MOCK,
            defaults={"created_by_id": actor_id, "status": PlatformIntegrationConfig.Status.DISABLED,
                      "network_enabled": False, "sync_read_enabled": False, "sync_write_enabled": False,
                      "platform_config": {"demo_snapshot": True}},
        )
        credential_fields = (config.credential_id, config.token_id, config.credential_mask,
                             config.credential_key_version, config.credential_fingerprint,
                             config.credential_operation_id_hash, config.credential_expires_at,
                             config.credential_revoked_at)
        if (config.status != "disabled" or config.network_enabled or config.sync_read_enabled
                or config.sync_write_enabled or any(credential_fields)
                or config.credential_status != "unconfigured" or config.callback_url):
            raise SnapshotImportError("existing demo integration config is not safely disabled")
        maps["configs"][source_id] = config
    batch_key = manifest_digest[:40]
    for source_platform_id, config in maps["configs"].items():
        job, _ = SyncJob.objects.get_or_create(
            tenant_id=tenant_id, integration_config=config, resource_type="sales_order",
            store_authorization=None, warehouse_authorization=None,
            defaults={"status": SyncJob.Status.DISABLED, "is_enabled": False,
                      "sync_scope": {"demo_snapshot": True}},
        )
        if job.is_enabled or job.status != SyncJob.Status.DISABLED:
            raise SnapshotImportError("existing demo sync job is enabled")
        run, _ = SyncRun.objects.get_or_create(
            tenant_id=tenant_id, sync_job=job,
            idempotency_key=f"demo-snapshot-{batch_key}-sales_order-{source_platform_id}"[:160],
            defaults={"run_id": f"demo-{batch_key}-sales_order-{source_platform_id}"[:80], "status": SyncRun.Status.SUCCESS},
        )
        maps["runs"][f"sales_order|{source_platform_id}"] = run
    # InventorySnapshot.clean requires its source job to be bound to the
    # warehouse platform, regardless of whether the source projection has a
    # service_platform field.  This local mock config has no credentials or IO.
    if records["inventory_snapshots"]:
        inventory_config, _ = PlatformIntegrationConfig.objects.get_or_create(
            tenant_id=tenant_id, platform="jifeng_wms",
            account_alias=f"demo-snapshot-jifeng-{batch_key[:8]}"[:120],
            environment=PlatformIntegrationConfig.Environment.MOCK,
            defaults={"created_by_id": actor_id, "status": PlatformIntegrationConfig.Status.DISABLED,
                      "network_enabled": False, "sync_read_enabled": False, "sync_write_enabled": False,
                      "platform_config": {"demo_snapshot": True}},
        )
        inventory_credentials = (inventory_config.credential_id, inventory_config.token_id,
                                 inventory_config.credential_mask, inventory_config.credential_key_version,
                                 inventory_config.credential_fingerprint, inventory_config.credential_operation_id_hash,
                                 inventory_config.credential_expires_at, inventory_config.credential_revoked_at)
        if (inventory_config.status != "disabled" or inventory_config.network_enabled
                or inventory_config.sync_read_enabled or inventory_config.sync_write_enabled
                or any(inventory_credentials)
                or inventory_config.credential_status != "unconfigured" or inventory_config.callback_url):
            raise SnapshotImportError("existing demo warehouse config is not safely disabled")
        inventory_job, _ = SyncJob.objects.get_or_create(
            tenant_id=tenant_id, integration_config=inventory_config, resource_type="inventory_snapshot",
            store_authorization=None, warehouse_authorization=None,
            defaults={"status": SyncJob.Status.DISABLED, "is_enabled": False,
                      "sync_scope": {"demo_snapshot": True}},
        )
        if inventory_job.is_enabled or inventory_job.status != SyncJob.Status.DISABLED:
            raise SnapshotImportError("existing demo warehouse sync job is enabled")
        maps["runs"]["inventory_snapshot"] = SyncRun.objects.get_or_create(
            tenant_id=tenant_id, sync_job=inventory_job,
            idempotency_key=f"demo-snapshot-{batch_key}-inventory_snapshot"[:160],
            defaults={"run_id": f"demo-{batch_key}-inventory_snapshot"[:80], "status": SyncRun.Status.SUCCESS},
        )[0]


def import_snapshot(bundle_dir: str | Path, *, tenant_id: int, actor_id: int, dry_run: bool = True) -> dict[str, Any]:
    """Import a verified bundle. Dry runs exercise writes inside a rolled-back transaction."""
    _database_allowed()
    from django.contrib.auth import get_user_model
    actor = get_user_model().objects.filter(pk=actor_id).only("tenant_id", "user_type", "is_active").first()
    if actor is None or actor.tenant_id != tenant_id or actor.user_type != "internal" or not actor.is_active:
        raise SnapshotImportError("actor must be an active internal user in the target tenant")
    manifest, records, manifest_digest = _read_bundle(bundle_dir)
    from apps.tenants.models import Tenant
    from .models import ImportedSnapshotReceipt, SnapshotIdentity
    maps: dict[str, dict[str, Any]] = {resource: {} for resource in RESOURCES}
    maps.update({"configs": {}, "runs": {}})
    summary = {"dry_run": bool(dry_run), "rows": sum(len(rows) for rows in records.values()),
               "created": 0, "updated": 0, "resources": {}, "site_mapping": "CountrySiteMaster imported; StoreMaster.platform_site left unset"}
    try:
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=tenant_id)
            receipt = ImportedSnapshotReceipt.objects.filter(tenant_id=tenant_id).first()
            if receipt:
                if receipt.manifest_sha256 != manifest_digest:
                    raise SnapshotImportError("tenant already has another imported snapshot; use a new demo database")
                summary.update({"created": 0, "updated": 0, "idempotent_replay": True})
                transaction.set_rollback(True)
                return summary
            if SnapshotIdentity.objects.filter(tenant_id=tenant_id).exists():
                raise SnapshotImportError("unreceipted snapshot identities exist; refusing to overwrite local rows")
            master_resources = ("platforms", "country_sites", "stores", "warehouses", "product_categories", "products", "product_details")
            fact_resources = ("sales_orders", "sales_order_items", "inventory_snapshots")
            for resource in master_resources:
                resource_created = resource_updated = 0
                resource_rows = _category_order(records[resource]) if resource == "product_categories" else records[resource]
                for row in resource_rows:
                    values = {key: value for key, value in row.items() if key != "id"}
                    _, created = _create_or_update(tenant_id, resource, row, values, actor_id, maps)
                    resource_created += int(created)
                    resource_updated += int(not created)
                summary["resources"][resource] = {"created": resource_created, "updated": resource_updated}
                summary["created"] += resource_created
                summary["updated"] += resource_updated
            _prepare_configs_and_runs(tenant_id, actor_id, records, manifest_digest, maps)
            for resource in fact_resources:
                resource_created = resource_updated = 0
                for row in records[resource]:
                    values = {key: value for key, value in row.items() if key != "id"}
                    _, created = _create_or_update(tenant_id, resource, row, values, actor_id, maps)
                    resource_created += int(created)
                    resource_updated += int(not created)
                summary["resources"][resource] = {"created": resource_created, "updated": resource_updated}
                summary["created"] += resource_created
                summary["updated"] += resource_updated
            if not dry_run:
                ImportedSnapshotReceipt.objects.create(tenant_id=tenant_id, manifest_sha256=manifest_digest)
            if dry_run:
                transaction.set_rollback(True)
    except SnapshotImportError:
        raise
    except Exception as exc:
        raise SnapshotImportError("snapshot import failed; transaction rolled back") from exc
    return summary
