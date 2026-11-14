"""Attach permission-scoped shared inventory observations to realtime board rows."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import F, Q, Subquery, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
from apps.products.models import ProductSKU
from apps.common.exceptions import DataScopeDenied
from .scopes import filter_inventory_queryset


_BASE_INVENTORY = {
    "available_qty": None,
    "status": "unavailable",
    "label": "库存不可用",
    "basis": "同站点已匹配仓共享库存",
    "warehouses": [],
    "coverage_days": None,
    "coverage_reason": "共享仓需求口径未齐，暂不计算",
}

_REASONS = {
    "unmapped": "商品未映射",
    "virtual": "虚拟商品不适用",
    "site_missing": "站点不明确",
    "stale": "没有24小时内的有效库存快照",
    "permission": "库存数据范围不可用",
}


def _inventory(status, qty=None, warehouses=None):
    labels = {
        "zero": "已匹配仓库存为0",
        "low": "已匹配仓库存偏低",
        "available": "已匹配仓有库存",
        "ambiguous": "来源编码有歧义，不能汇总库存",
        "partial": "部分 SKU 库存已知",
    }
    return {
        **_BASE_INVENTORY,
        "available_qty": qty,
        "status": status,
        "label": labels.get(status, _REASONS.get(status, "库存不可用")),
        "warehouses": warehouses or [],
    }


def _rows(group):
    found = {}
    for key in ("sku_ranking", "sku_rankings"):
        value = group.get(key, [])
        if isinstance(value, dict):
            value = [row for rows in value.values() if isinstance(rows, list) for row in rows]
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    found[id(row)] = row
    for dimension, metrics in group.get("product_rankings", {}).items():
        if dimension not in {"product_sku", "store_sku", "product_spu", "store_spu", "category"}:
            for rows in metrics.values():
                for row in rows if isinstance(rows, list) else []:
                    if isinstance(row, dict):
                        row["inventory"] = {
                            **_BASE_INVENTORY,
                            "status": "aggregate_pending",
                            "label": "汇总维度暂不计算库存",
                            "basis": "商品维度聚合可能包含多个 SKU 或共享库存",
                            "coverage_reason": "维度未对应唯一 SKU，暂不计算",
                        }
            continue
        for rows in metrics.values():
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    found[id(row)] = row
    return list(found.values())


def attach_board_inventory(request, groups):
    """Mutate board groups with inventory facts scoped to the caller.

    Query count is independent of the number of rows: candidate identities from
    all currency groups share one bounded inventory query.
    """
    group_values = list(groups.values()) if isinstance(groups, dict) else list(groups)
    grouped_rows = []
    for group in group_values:
        rows = _rows(group)
        grouped_rows.append((group, rows))
        for row in rows:
            row["inventory"] = _inventory("unmapped" if not row.get("internal_sku_id") else "stale")

    tenant_id = getattr(getattr(request.user, "tenant", None), "id", None)
    if not tenant_id:
        return groups

    candidates = {}
    spu_children = defaultdict(list)
    for group, rows in grouped_rows:
        for row in rows:
            sku_id = row.get("internal_sku_id")
            if not sku_id:
                continue
            if row.get("inventory_type") == "virtual":
                row["inventory"] = _inventory("virtual")
                continue
            site = row.get("inventory_site")
            if not site:
                row["inventory"] = _inventory("site_missing")
                continue
            candidates.setdefault((site, sku_id), []).append(row)

    # SPU inventory includes every physical child SKU, including SKUs with no
    # sales in this period. Each (country, SKU) is counted once regardless of
    # how many stores or currency groups reference the SPU.
    spu_rows = defaultdict(list)
    spu_row_children = defaultdict(list)
    category_rows = defaultdict(list)
    for _, rows in grouped_rows:
        for row in rows:
            spu_id = row.get("mapped_spu_id")
            if spu_id and all(existing is not row for existing in spu_rows[spu_id]):
                spu_rows[spu_id].append(row)
            category_id = row.get("inventory_category_id")
            if category_id and all(existing is not row for existing in category_rows[category_id]):
                category_rows[category_id].append(row)
    if spu_rows:
        children = ProductSKU.objects.filter(tenant_id=tenant_id, spu_id__in=spu_rows).exclude(inventory_type="virtual").values_list("id", "spu_id")
        for sku_id, spu_id in children:
            for row in spu_rows[spu_id]:
                for country in row.get("inventory_countries", []):
                    synthetic = {"internal_sku_id": sku_id, "inventory_site": country, "inventory_type": "physical"}
                    candidates.setdefault((country, sku_id), []).append(synthetic)
                    spu_row_children[id(row)].append((country, sku_id, synthetic))
        for rows in spu_rows.values():
            for row in rows:
                row["inventory"] = _inventory("partial")
                row["inventory"].update(partial=True, country_breakdown=[])

    # Category stock is the union of physical SKUs in mapped SPUs assigned to
    # the category, deduplicated by SKU and country before candidate lookup.
    category_row_children = defaultdict(list)
    if category_rows:
        category_spus = defaultdict(list)
        mapped_spus = {spu_id for rows in category_rows.values() for row in rows for spu_id in row.get("inventory_spu_ids", [])}
        for spu_id, category_id in ProductSKU.objects.filter(
            tenant_id=tenant_id, spu__tenant_id=tenant_id, spu_id__in=mapped_spus,
            spu__category_node__tenant_id=tenant_id,
        ).exclude(inventory_type="virtual").values_list("spu_id", "spu__category_node_id").distinct():
            category_spus[category_id].append(spu_id)
        child_rows = ProductSKU.objects.filter(
            tenant_id=tenant_id, spu_id__in={spu_id for ids in category_spus.values() for spu_id in ids},
        ).exclude(inventory_type="virtual").values_list("id", "spu_id")
        children_by_spu = defaultdict(list)
        for sku_id, spu_id in child_rows:
            children_by_spu[spu_id].append(sku_id)
        for category_id, rows in category_rows.items():
            for row in rows:
                seen = set()
                for spu_id in set(category_spus[category_id]) & set(row.get("inventory_spu_ids", [])):
                    for sku_id in children_by_spu[spu_id]:
                        for country in row.get("inventory_countries", []):
                            identity = (country, sku_id)
                            if identity in seen:
                                continue
                            seen.add(identity)
                            child = {"internal_sku_id": sku_id, "inventory_site": country, "inventory_type": "physical"}
                            candidates.setdefault(identity, []).append(child)
                            category_row_children[id(row)].append((country, sku_id, child))
                row["inventory"] = _inventory("partial")
                row["inventory"].update(partial=True, country_breakdown=[])

    if not candidates:
        return groups
    try:
        base = InventorySnapshot.objects.filter(tenant_id=tenant_id)
        scoped = filter_inventory_queryset(
            request.user, "sales_management.view", base,
            getattr(request, "_permission_resolution_cache", None),
        )
    except DataScopeDenied:
        for rows in candidates.values():
            for row in rows:
                row["inventory"] = _inventory("permission")
        for rows in spu_rows.values():
            for row in rows:
                row["inventory"] = _inventory("permission")
                row["inventory"].update(partial=True, country_breakdown=[])
        return groups

    # Materialize each site's candidate source codes before ranking. This keeps
    # the identity lookup out of the windowed history query while still ranking
    # complete histories before mapping, status, recency or permission filters.
    candidate_by_site = defaultdict(set)
    for site, sku_id in candidates:
        candidate_by_site[site].add(sku_id)
    identity_filter = Q(pk__in=[])
    for site, sku_ids in candidate_by_site.items():
        source_codes = list(base.filter(
            site_code=site, internal_sku_id__in=sku_ids,
        ).order_by().values_list("source_sku", flat=True).distinct())
        if source_codes:
            identity_filter |= Q(site_code=site, source_sku__in=source_codes)
    history = base.filter(identity_filter).order_by().annotate(
        _latest=Window(
            expression=RowNumber(),
            partition_by=[F("site_code"), F("warehouse_id"), F("source_sku")],
            order_by=[F("snapshot_at_utc").desc(), F("pk").desc()],
        )
    ).filter(_latest=1)
    wanted_pairs = Q(pk__in=[])
    for site, sku_ids in candidate_by_site.items():
        wanted_pairs |= Q(site_code=site, internal_sku_id__in=sku_ids)
    latest_records = scoped.filter(pk__in=Subquery(history.values("pk"))).filter(
        wanted_pairs, warehouse__tenant_id=tenant_id, warehouse__status="active",
        warehouse__country_code__iexact=F("site_code"),
    ).order_by().values(
        "site_code", "internal_sku_id", "warehouse_id", "warehouse__name", "source_sku",
        "available_qty", "in_transit_qty", "provided_quantity_fields", "snapshot_at_utc",
        "source_run__tenant_id", "source_run__status", "source_run__failed_count",
        "source_run__sync_job__resource_type", "source_run__sync_job__integration_config__platform",
    )
    results = defaultdict(list)
    now = timezone.now()
    for record in latest_records:
        results[(record["site_code"], record["internal_sku_id"])].append(record)

    for identity, rows in candidates.items():
        facts = results.get(identity, [])
        if not facts:
            for row in rows:
                row["inventory"] = _inventory("permission" if scoped.query.is_empty() else "stale")
            continue
        valid = [fact for fact in facts if (
            fact["source_run__tenant_id"] == tenant_id
            and fact["source_run__status"] == "success"
            and fact["source_run__failed_count"] == 0
            and fact["source_run__sync_job__resource_type"] == "inventory_snapshot"
            and fact["source_run__sync_job__integration_config__platform"] == "jifeng_wms"
            and ("available_qty" in (fact["provided_quantity_fields"] or []) or "in_transit_qty" in (fact["provided_quantity_fields"] or []))
            and now - timedelta(hours=24) <= fact["snapshot_at_utc"] <= now
        )]
        if len(valid) != len(facts):
            for row in rows:
                row["inventory"] = _inventory("stale")
            continue
        warehouse_rows = defaultdict(list)
        for fact in facts:
            warehouse_rows[fact["warehouse_id"]].append(fact)
        warehouses = []
        ambiguous = False
        for warehouse_id, warehouse_facts in warehouse_rows.items():
            if len({fact["source_sku"] for fact in warehouse_facts}) != 1:
                ambiguous = True
                warehouses.append({"id": warehouse_id, "name": warehouse_facts[0]["warehouse__name"],
                                   "available_qty": None, "status": "ambiguous"})
                continue
            fields = warehouse_facts[0]["provided_quantity_fields"] or []
            qty = int(warehouse_facts[0]["available_qty"]) if "available_qty" in fields else None
            transit = int(warehouse_facts[0]["in_transit_qty"] or 0) if "in_transit_qty" in fields else None
            status = "unavailable" if qty is None else "zero" if qty == 0 else "low" if qty <= 5 else "available"
            warehouse = {"id": warehouse_id, "name": warehouse_facts[0]["warehouse__name"],
                         "available_qty": qty, "status": status}
            if transit is not None:
                warehouse["in_transit_qty"] = transit
            warehouses.append(warehouse)
        if ambiguous:
            inventory = _inventory("ambiguous", warehouses=warehouses)
        else:
            known_available = [item["available_qty"] for item in warehouses if item["available_qty"] is not None]
            total = sum(known_available) if known_available else None
            status = "partial" if any(item["available_qty"] is None for item in warehouses) else "zero" if total == 0 else "low" if total <= 5 else "available"
            inventory = _inventory(status, total, warehouses)
            inventory["partial"] = any(item["available_qty"] is None for item in warehouses)
        transit_values = [item.get("in_transit_qty") for item in warehouses]
        known_transit = [value for value in transit_values if value is not None]
        if known_transit:
            inventory["in_transit_qty"] = sum(known_transit)
        inventory["transit_partial"] = any(value is None for value in transit_values)
        for row in rows:
            row["inventory"] = inventory
    for row_id, children in spu_row_children.items():
        country_totals = defaultdict(int)
        country_transit = defaultdict(int)
        transit_known = defaultdict(bool)
        warehouses = {}
        partial = False
        for country, sku_id, child in children:
            inv = child.get("inventory", {})
            if inv.get("partial") or inv.get("available_qty") is None:
                partial = True
            if inv.get("available_qty") is not None:
                country_totals[country] += inv["available_qty"]
            if inv.get("in_transit_qty") is not None:
                country_transit[country] += inv["in_transit_qty"]
                transit_known[country] = True
            for wh in inv.get("warehouses", []):
                key = (country, wh["id"])
                if key not in warehouses:
                    warehouses[key] = {**wh, "country": country}
                else:
                    if warehouses[key].get("available_qty") is not None and wh.get("available_qty") is not None:
                        warehouses[key]["available_qty"] += wh["available_qty"]
                    else:
                        warehouses[key]["available_qty"] = None
                    if wh.get("in_transit_qty") is not None:
                        warehouses[key]["in_transit_qty"] = (warehouses[key].get("in_transit_qty") or 0) + wh["in_transit_qty"]
        total = sum(country_totals.values()) if country_totals else None
        transit_partial = any((child.get("inventory", {}).get("transit_partial") or child.get("inventory", {}).get("in_transit_qty") is None) for _, _, child in children)
        status = "partial" if partial else "zero" if total == 0 else "low" if total <= 5 else "available"
        inventory = _inventory(status, total, list(warehouses.values()))
        inventory.update(partial=partial, transit_partial=transit_partial,
                         country_breakdown=[{"country": country, "available_qty": qty} for country, qty in sorted(country_totals.items())])
        if country_transit:
            inventory["in_transit_qty"] = sum(country_transit.values())
            for row_country in inventory["country_breakdown"]:
                row_country["in_transit_qty"] = country_transit.get(row_country["country"])
        for rows in spu_rows.values():
            for row in rows:
                if id(row) == row_id:
                    row["inventory"] = inventory
                    break
    for row_id, children in category_row_children.items():
        country_totals = defaultdict(int)
        country_transit = defaultdict(int)
        transit_known = defaultdict(bool)
        warehouses = {}
        partial = False
        for country, sku_id, child in children:
            inv = child.get("inventory", {})
            if inv.get("partial") or inv.get("available_qty") is None:
                partial = True
            if inv.get("available_qty") is not None:
                country_totals[country] += inv["available_qty"]
            if inv.get("in_transit_qty") is not None:
                country_transit[country] += inv["in_transit_qty"]
                transit_known[country] = True
            for wh in inv.get("warehouses", []):
                key = (country, wh["id"])
                if key not in warehouses:
                    warehouses[key] = {**wh, "country": country}
                else:
                    if warehouses[key].get("available_qty") is not None and wh.get("available_qty") is not None:
                        warehouses[key]["available_qty"] += wh["available_qty"]
                    else:
                        warehouses[key]["available_qty"] = None
                    if wh.get("in_transit_qty") is not None:
                        warehouses[key]["in_transit_qty"] = (warehouses[key].get("in_transit_qty") or 0) + wh["in_transit_qty"]
        total = sum(country_totals.values()) if country_totals else None
        inventory = _inventory("partial" if partial else "zero" if total == 0 else "low" if total <= 5 else "available", total, list(warehouses.values()))
        transit_total = sum(country_transit.values()) if country_transit and all(transit_known.values()) else None
        inventory.update(partial=partial,
                         country_breakdown=[{"country": country, "available_qty": qty} for country, qty in sorted(country_totals.items())])
        inventory["transit_partial"] = any((child.get("inventory", {}).get("transit_partial") or child.get("inventory", {}).get("in_transit_qty") is None) for _, _, child in children)
        if country_transit:
            transit_total = sum(country_transit.values())
            inventory["in_transit_qty"] = transit_total
            for row_country in inventory["country_breakdown"]:
                row_country["in_transit_qty"] = country_transit.get(row_country["country"])
        for _, rows in grouped_rows:
            for row in rows:
                if id(row) == row_id:
                    row["inventory"] = inventory
                    break
    return groups
