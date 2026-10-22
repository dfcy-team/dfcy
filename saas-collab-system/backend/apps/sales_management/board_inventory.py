"""Attach permission-scoped shared inventory observations to realtime board rows."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import F, Q, Subquery, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from apps.commerce.models import InventorySnapshot
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
        return groups

    # Use a bounded non-correlated source_sku subquery for each candidate site,
    # then rank complete histories for those identities before any mapping,
    # status, recency or permission predicates are applied.
    candidate_by_site = defaultdict(set)
    for site, sku_id in candidates:
        candidate_by_site[site].add(sku_id)
    identity_filter = Q(pk__in=[])
    for site, sku_ids in candidate_by_site.items():
        source_codes = base.filter(site_code=site, internal_sku_id__in=sku_ids).order_by().values("source_sku")
        identity_filter |= Q(site_code=site, source_sku__in=Subquery(source_codes))
    history = base.filter(identity_filter).order_by().annotate(
        _latest=Window(
            expression=RowNumber(),
            partition_by=[F("site_code"), F("warehouse_id"), F("source_sku")],
            order_by=[F("snapshot_at_utc").desc(), F("pk").desc()],
        )
    ).filter(_latest=1)
    wanted_pairs = Q(pk__in=[])
    for site, sku_id in candidates:
        wanted_pairs |= Q(site_code=site, internal_sku_id=sku_id)
    latest_records = scoped.filter(pk__in=Subquery(history.values("pk"))).filter(
        wanted_pairs, warehouse__tenant_id=tenant_id, warehouse__status="active",
        warehouse__country_code__iexact=F("site_code"),
    ).order_by().values(
        "site_code", "internal_sku_id", "warehouse_id", "warehouse__name", "source_sku",
        "available_qty", "provided_quantity_fields", "snapshot_at_utc",
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
            and "available_qty" in (fact["provided_quantity_fields"] or [])
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
            qty = int(warehouse_facts[0]["available_qty"])
            status = "zero" if qty == 0 else "low" if qty <= 5 else "available"
            warehouses.append({"id": warehouse_id, "name": warehouse_facts[0]["warehouse__name"],
                               "available_qty": qty, "status": status})
        if ambiguous:
            inventory = _inventory("ambiguous", warehouses=warehouses)
        else:
            total = sum(item["available_qty"] for item in warehouses)
            status = "zero" if total == 0 else "low" if total <= 5 else "available"
            inventory = _inventory(status, total, warehouses)
        for row in rows:
            row["inventory"] = inventory
    return groups
