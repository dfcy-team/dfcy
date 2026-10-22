"""Build a bounded, de-identified JSONL snapshot from the demo source API.

Only fields declared below cross the source boundary.  The source API must
already be authenticated for one tenant; this module additionally applies the
requested store/warehouse scope before writing any artifact.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "demo-snapshot.v1"
RESOURCES = (
    "platforms", "country_sites", "stores", "warehouses", "product_categories",
    "products", "product_details", "sales_orders", "sales_order_items",
    "inventory_snapshots",
)
PAGE_LIMIT = 1000
RESOURCE_ROW_LIMIT = 100_000
TOTAL_ROW_LIMIT = 250_000

# `id` and `*_id` are opaque source relationship keys needed for mapping.  The
# human/business identity fields are HMAC tokens, and URLs are never admitted.
FIELDS: dict[str, frozenset[str]] = {
    "platforms": frozenset("id code name platform_type status".split()),
    "country_sites": frozenset("id code name country_code currency timezone status".split()),
    "stores": frozenset("id code name external_store_id platform_id platform_type country_code currency settlement_currency timezone status".split()),
    "warehouses": frozenset("id code name country_code warehouse_type service_platform_id platform_id address region status".split()),
    "product_categories": frozenset("id parent_id level code name english_name platform_category_id spec_dimensions is_active".split()),
    "products": frozenset("id spu_id sku_id category_id category_node_id spu_code sku_code product_name brand category product_type lifecycle_status sales_status first_sale_date is_active".split()),
    "product_details": frozenset("id product_id sku_id spu_id sku_code product_name color_code specification spec_values size material package_weight package_volume purchase_price unit package_length_cm package_width_cm package_height_cm origin_country hs_code inventory_type product_description is_active".split()),
    "sales_orders": frozenset("id platform_id store_id external_order_id region raw_status normalized_status status_mapping_version created_at_utc updated_at_utc paid_at_utc delivered_at_utc cancelled_at_utc completed_at_utc business_date currency subtotal_amount seller_discount_amount platform_discount_amount shipping_amount tax_amount order_total_amount".split()),
    "sales_order_items": frozenset("id sales_order_id order_id internal_spu_id internal_sku_id external_line_id platform_product_id platform_variant_id seller_sku item_name_snapshot variation_snapshot quantity original_unit_price sale_unit_price discount_amount tax_amount line_total_amount currency raw_line_status".split()),
    "inventory_snapshots": frozenset("id site_code country_code warehouse_id internal_sku_id source_sku platform_product_id platform_variant_id seller_sku on_hand_qty available_qty reserved_qty in_transit_qty pending_putaway_qty defective_qty provided_quantity_fields snapshot_at_utc".split()),
}
IDENTITY_FIELDS = frozenset({
    "code", "name", "external_store_id", "spu_code", "sku_code", "product_name",
    "brand", "category", "english_name", "platform_category_id", "external_order_id",
    "external_line_id", "platform_product_id", "platform_variant_id", "seller_sku",
    "item_name_snapshot", "variation_snapshot", "source_sku", "address",
})
RELATIONSHIPS: dict[str, tuple[str, ...]] = {
    "platforms": (), "country_sites": ("platform_id",),
    "stores": ("platform_id",),
    "warehouses": ("service_platform_id", "platform_id"),
    "product_categories": ("parent_id",),
    "products": ("category_id", "category_node_id"),
    "product_details": ("product_id", "sku_id", "spu_id"),
    "sales_orders": ("platform_id", "store_id"),
    "sales_order_items": ("sales_order_id", "order_id", "internal_spu_id", "internal_sku_id"),
    "inventory_snapshots": ("warehouse_id", "internal_sku_id"),
}
ID_ALIASES = {
    "sales_order_items": {"order_id": "sales_order_id"},
    "products": {"category_id": "category_node_id"},
    "product_details": {"product_id": "spu_id"},
}
DEPENDENCIES = {
    "platforms": {"platforms"},
    "country_sites": {"country_sites"},
    "stores": {"stores", "platforms", "country_sites"},
    "warehouses": {"warehouses", "platforms", "country_sites"},
    "product_categories": {"product_categories"},
    "products": {"products", "product_categories", "product_details"},
    "product_details": {"product_details", "products", "product_categories"},
    "sales_orders": {"sales_orders", "sales_order_items", "stores", "platforms", "country_sites", "products", "product_details", "product_categories"},
    "sales_order_items": {"sales_orders", "sales_order_items", "stores", "platforms", "country_sites", "products", "product_details", "product_categories"},
    "inventory_snapshots": {"inventory_snapshots", "warehouses", "products", "product_details", "product_categories"},
}


class SnapshotError(ValueError):
    """The source response cannot produce a safe, self-contained snapshot."""


def _token(key: bytes, field: str, value: Any) -> str:
    raw = str(value).encode("utf-8")
    return "demo_" + hmac.new(key, field.encode() + b"\0" + raw, hashlib.sha256).hexdigest()[:24]


def _safe_record(resource: str, record: Any, key: bytes) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SnapshotError(f"{resource} item must be an object")
    if "id" not in record or record["id"] in (None, ""):
        raise SnapshotError(f"{resource} item has no id")
    fields = FIELDS[resource]
    result = {name: value for name, value in record.items() if name in fields}
    mask_fields = IDENTITY_FIELDS.intersection(result)
    if resource == "product_categories":
        # Category codes are structural (one or two digits) and are required
        # by ProductCategory's model validation; category names are masked.
        mask_fields = mask_fields - {"code"}
    for field in mask_fields:
        value = result[field]
        if value not in (None, ""):
            namespace = "sku" if field in {"sku_code", "seller_sku", "source_sku"} else field
            result[field] = _token(key, namespace, value)
    return result


def _canonical_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _collect(client: Any, resource: str, params: dict[str, Any], callback: Callable[[int], None] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = None
    seen_cursors: set[str] = set()
    while True:
        request = dict(params)
        if cursor is not None:
            request["cursor"] = cursor
        data = client.fetch(resource, request)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise SnapshotError(f"{resource} response must contain data.items")
        items = data["items"]
        if len(items) > PAGE_LIMIT:
            raise SnapshotError(f"{resource} page exceeds {PAGE_LIMIT} rows")
        rows.extend(items)
        if len(rows) > RESOURCE_ROW_LIMIT:
            raise SnapshotError(f"{resource} exceeds the resource row limit")
        if callback:
            callback(len(items))
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
        if next_cursor in (None, "") or str(next_cursor) in seen_cursors:
            raise SnapshotError(f"{resource} pagination cursor is missing or repeated")
        cursor = next_cursor
        seen_cursors.add(str(cursor))
    return rows


def _scope_records(records: dict[str, list[dict[str, Any]]], store_ids: set[str], warehouse_ids: set[str], requested: set[str], selected: set[str]) -> dict[str, list[dict[str, Any]]]:
    # First constrain roots and then take only their platform/site and fact
    # dependencies.  No out-of-scope master record is written to disk.
    stores = [r for r in records["stores"] if _canonical_id(r.get("id")) in store_ids] if "stores" in requested else []
    warehouses = [r for r in records["warehouses"] if _canonical_id(r.get("id")) in warehouse_ids] if "warehouses" in requested else []
    store_ids_found = {_canonical_id(r["id"]) for r in stores}
    warehouse_ids_found = {_canonical_id(r["id"]) for r in warehouses}
    if "stores" in requested and store_ids - store_ids_found:
        raise SnapshotError("one or more requested stores were not returned by the source")
    if "warehouses" in requested and warehouse_ids - warehouse_ids_found:
        raise SnapshotError("one or more requested warehouses were not returned by the source")

    sales_orders = [r for r in records["sales_orders"] if _canonical_id(r.get("store_id")) in store_ids_found]
    order_ids = {_canonical_id(r["id"]) for r in sales_orders}
    sales_items = [r for r in records["sales_order_items"] if _canonical_id(r.get("sales_order_id", r.get("order_id"))) in order_ids]
    inventory = [r for r in records["inventory_snapshots"] if _canonical_id(r.get("warehouse_id")) in warehouse_ids_found]

    platform_ids = {_canonical_id(r.get("platform_id")) for r in stores} | {_canonical_id(r.get("service_platform_id", r.get("platform_id"))) for r in warehouses}
    country_codes = {str(r.get("country_code", "")).upper() for r in stores + warehouses if r.get("country_code")}
    platforms = [r for r in records["platforms"] if "platforms" in selected or _canonical_id(r.get("id")) in platform_ids]
    sites = [r for r in records["country_sites"] if "country_sites" in selected or str(r.get("country_code", "")).upper() in country_codes]
    # Facts drive the product subset, which in turn drives the category tree.
    product_ids = {_canonical_id(r.get("internal_sku_id")) for r in sales_items + inventory if r.get("internal_sku_id")}
    spu_ids = {_canonical_id(r.get("internal_spu_id")) for r in sales_items if r.get("internal_spu_id")}
    related_details = [r for r in records["product_details"] if "product_details" in selected or _canonical_id(r.get("id")) in product_ids]
    spu_ids.update(_canonical_id(r.get("spu_id")) for r in related_details if r.get("spu_id"))
    direct_products = [r for r in records["products"] if "products" in selected or _canonical_id(r.get("id")) in product_ids | spu_ids]
    # API may represent each product row as an SKU with an SPU id; include
    # all variants of referenced SPUs to keep the product hierarchy coherent.
    parent_ids = {_canonical_id(r.get("spu_id")) for r in direct_products if r.get("spu_id")}
    products = [r for r in records["products"] if "products" in selected or _canonical_id(r.get("id")) in product_ids | spu_ids | parent_ids]
    selected_spu_ids = {_canonical_id(r.get("id")) for r in products}
    detail_ids = {_canonical_id(r.get("id")) for r in products} | product_ids
    details = [r for r in records["product_details"]
               if _canonical_id(r.get("sku_id", r.get("product_id", r.get("id")))) in detail_ids
               or bool({"product_details", "products"}.intersection(selected))
               or _canonical_id(r.get("id")) in detail_ids
               or _canonical_id(r.get("spu_id")) in selected_spu_ids]
    category_ids = {_canonical_id(r.get("category_node_id", r.get("category_id"))) for r in products if r.get("category_node_id", r.get("category_id"))}
    category_by_id = {_canonical_id(r.get("id")): r for r in records["product_categories"]}
    pending = list(category_ids)
    while pending:
        category = category_by_id.get(pending.pop())
        if category and category.get("parent_id"):
            parent_id = _canonical_id(category["parent_id"])
            if parent_id not in category_ids:
                category_ids.add(parent_id)
                pending.append(parent_id)
    categories = [r for r in records["product_categories"] if "product_categories" in selected or _canonical_id(r.get("id")) in category_ids]

    result = {key: [] for key in RESOURCES}
    result.update({"platforms": platforms, "country_sites": sites, "stores": stores, "warehouses": warehouses,
                   "product_categories": categories, "products": products, "product_details": details,
                   "sales_orders": sales_orders, "sales_order_items": sales_items, "inventory_snapshots": inventory})
    # Keep countries/platforms only if needed by in-scope root objects; all
    # other source rows are dropped before serialization.
    return result


def _validate_relations(rows: dict[str, list[dict[str, Any]]]) -> None:
    ids = {resource: {_canonical_id(row.get("id")) for row in items} for resource, items in rows.items()}
    for resource, items in rows.items():
        if len(ids[resource]) != len(items):
            raise SnapshotError(f"{resource} contains duplicate ids")
        if any(not source_id or len(source_id) > 64 for source_id in ids[resource]):
            raise SnapshotError(f"{resource} source ids must contain 1 to 64 characters")
        for row in items:
            for field in RELATIONSHIPS[resource]:
                value = row.get(field)
                if value in (None, ""):
                    continue
                target_resource = {
                    "platform_id": "platforms", "service_platform_id": "platforms",
                    "platform_site_id": "country_sites", "country_site_id": "country_sites",
                    "parent_id": "product_categories", "category_id": "product_categories",
                    "category_node_id": "product_categories", "product_id": "products",
                    "sku_id": "products", "spu_id": "products", "store_id": "stores",
                    "warehouse_id": "warehouses", "sales_order_id": "sales_orders",
                    "order_id": "sales_orders", "internal_spu_id": "products",
                    "internal_sku_id": "product_details",
                }[field]
                if _canonical_id(value) not in ids[target_resource]:
                    raise SnapshotError(f"{resource}.{field} refers to missing relationships or an out-of-scope record")
    categories = {_canonical_id(row["id"]): row for row in rows["product_categories"]}
    completed: set[str] = set()
    for source_id in categories:
        current = source_id
        path: set[str] = set()
        while current in categories and current not in completed:
            if current in path:
                raise SnapshotError("product_categories contains a parent cycle")
            path.add(current)
            parent = categories[current].get("parent_id")
            if parent in (None, ""):
                break
            current = _canonical_id(parent)
        completed.update(path)


def build_snapshot(*, client: Any, resources: Iterable[str], store_ids: Iterable[Any], warehouse_ids: Iterable[Any], date_from: Any, date_to: Any, output_dir: str | os.PathLike[str], scope_key: str, checkpoint: Any = None, progress: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Fetch and publish a consistent, de-identified snapshot.

    Checkpoint input is intentionally ignored: a new batch is always re-read
    from page one until a stable continuation protocol is available.
    """
    del checkpoint
    key = getattr(client, "masking_key", None)
    if not isinstance(key, bytes) or len(key) < 32:
        raise SnapshotError("client.masking_key must be at least 32 secret bytes")
    if not scope_key or not isinstance(scope_key, str):
        raise SnapshotError("scope_key is required")
    requested = set(resources or ())
    unknown = requested - set(RESOURCES)
    if unknown:
        raise SnapshotError("unknown resource requested")
    selected = set(requested)
    requested = set().union(*(DEPENDENCIES[item] for item in selected)) if selected else set()
    stores_scope = {_canonical_id(value) for value in store_ids}
    warehouses_scope = {_canonical_id(value) for value in warehouse_ids}
    if ("sales_orders" in requested or "sales_order_items" in requested) and not stores_scope:
        raise SnapshotError("store scope is required for order resources")
    if "inventory_snapshots" in requested and not warehouses_scope:
        raise SnapshotError("warehouse scope is required for inventory resources")
    if not requested:
        raise SnapshotError("at least one store or warehouse scope is required")
    page_limit = getattr(client, "page_size_limit", PAGE_LIMIT)
    if type(page_limit) is not int or not 1 <= page_limit <= PAGE_LIMIT:
        raise SnapshotError("client page_size_limit must be between 1 and 1000")
    raw: dict[str, list[dict[str, Any]]] = {resource: [] for resource in RESOURCES}
    total = 0
    for resource in RESOURCES:
        if resource not in requested:
            continue
        def report(count: int, name: str = resource) -> None:
            nonlocal total
            total += count
            if total > TOTAL_ROW_LIMIT:
                raise SnapshotError("snapshot exceeds total row limit")
            if progress:
                progress(name, total, count)
        params_list = []
        if resource in {"sales_orders", "sales_order_items"}:
            params_list = [{"store_id": store_id, "date_from": str(date_from), "date_to": str(date_to), "limit": page_limit} for store_id in sorted(stores_scope)]
        elif resource == "inventory_snapshots":
            params_list = [{"warehouse_id": warehouse_id, "date_from": str(date_from), "date_to": str(date_to), "limit": page_limit} for warehouse_id in sorted(warehouses_scope)]
        else:
            params_list = [{"limit": page_limit}]
        dedup: dict[str, dict[str, Any]] = {}
        for params in params_list:
            for row in _collect(client, resource, params, report):
                if not isinstance(row, dict) or row.get("id") in (None, ""):
                    raise SnapshotError(f"{resource} item must contain an id")
                dedup.setdefault(_canonical_id(row["id"]), row)
        raw[resource] = list(dedup.values())
    scoped = _scope_records(raw, stores_scope, warehouses_scope, requested, selected)
    safe = {resource: [_safe_record(resource, row, key) for row in scoped[resource]] for resource in RESOURCES}
    # Normalize known source relation aliases after validation selection.
    for resource, aliases in ID_ALIASES.items():
        for row in safe[resource]:
            for source, target in aliases.items():
                if target not in row and source in row:
                    row[target] = row[source]
                row.pop(source, None)
    _validate_relations(safe)

    # Build off to the side and publish only a complete manifest+file set.
    output = Path(output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    files = []
    try:
        for resource in RESOURCES:
            path = temp / f"{resource}.jsonl"
            digest = hashlib.sha256()
            count = 0
            with path.open("wb") as handle:
                for row in safe[resource]:
                    line = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                    handle.write(line)
                    digest.update(line)
                    count += 1
            files.append({"resource": resource, "path": path.name, "count": count, "sha256": digest.hexdigest()})
        manifest = {"schema_version": SCHEMA_VERSION, "scope_key": scope_key,
                    "window": {"date_from": str(date_from), "date_to": str(date_to)},
                    "consistent": False, "deidentified": True, "files": files,
                    "summary": {"rows": sum(f["count"] for f in files), "resources": len(files)}}
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
                raise SnapshotError("output_dir must be missing or an empty directory")
            output.rmdir()
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return manifest
