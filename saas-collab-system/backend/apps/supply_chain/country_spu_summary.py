"""Read-only country + SPU stock/listing risk summaries for authorized SKU scope."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal


def _stock_by_sku_warehouse(records, *, now, max_age=timedelta(hours=24)):
    """Select at most one source identity per SKU/warehouse; flag alias ambiguity."""
    grouped = defaultdict(list)
    for row in records:
        grouped[(row.internal_sku_id, row.warehouse_id)].append(row)
    by_sku = defaultdict(lambda: {
        "on_hand": Decimal(0), "available": Decimal(0), "in_transit": Decimal(0),
        "pending_putaway": Decimal(0), "known_warehouses": 0, "complete": True,
        "issues": [], "virtual_on_hand": Decimal(0), "virtual_available": Decimal(0),
    })
    for (sku_id, _warehouse_id), candidates in grouped.items():
        row = max(candidates, key=lambda r: (r.snapshot_at_utc, r.pk))
        item = by_sku[sku_id]
        aliases = {r.source_sku for r in candidates}
        problems = []
        if len(aliases) != 1:
            problems.append("ambiguous_inventory_aliases")
        if row.source_run.status != "success" or row.source_run.failed_count:
            problems.append("inventory_source_incomplete")
        if row.snapshot_at_utc < now - max_age:
            problems.append("stale_inventory_snapshot")
        supplied = set(row.provided_quantity_fields or ())
        required = {"on_hand_qty", "available_qty"}
        if not required.issubset(supplied):
            problems.append("inventory_quantity_unverified")
        if problems:
            item["complete"] = False
            item["issues"].extend(problems)
            continue
        item["known_warehouses"] += 1
        target = item
        virtual = getattr(row.internal_sku, "inventory_type", None) == "virtual"
        if virtual:
            target = {"virtual_on_hand": item["virtual_on_hand"], "virtual_available": item["virtual_available"]}
            target["virtual_on_hand"] += Decimal(row.on_hand_qty)
            target["virtual_available"] += Decimal(row.available_qty)
            item["virtual_on_hand"], item["virtual_available"] = target["virtual_on_hand"], target["virtual_available"]
            continue
        item["on_hand"] += Decimal(row.on_hand_qty)
        item["available"] += Decimal(row.available_qty)
        item["in_transit"] += Decimal(row.in_transit_qty or 0)
        item["pending_putaway"] += Decimal(row.pending_putaway_qty or 0)
    return dict(by_sku)


def country_spu_summary(actor, country, skus, *, now=None):
    """Summarize every SKU visible for each represented SPU in this country.

    The result explicitly describes authorized-scope coverage. It never infers
    country-wide zero stock/listing from a narrower data scope.
    """
    from django.utils import timezone
    from apps.commerce import country_decisions as cd
    from apps.sales_management.inventory_queries import latest_country_inventory
    from apps.sales_management.scopes import filter_inventory_queryset
    from apps.permissions.services import check_user_permission
    from apps.products.models import ProductSPU
    from .country_listing_evidence import country_listing_evidence
    from .inventory_listing_risk import classify_country_risk

    now = now or timezone.now()
    tenant_id = actor.tenant_id
    requested = {sku.pk for sku in skus if getattr(sku, "tenant_id", tenant_id) == tenant_id}
    if not requested:
        return {}
    authorized = cd.skus_for(actor, country)
    requested_authorized = list(authorized.filter(pk__in=requested).select_related("spu"))
    spu_ids = {sku.spu_id for sku in requested_authorized}
    visible_skus = list(authorized.filter(spu_id__in=spu_ids)
        .select_related("spu").order_by("spu_id", "pk"))
    visible_ids = {sku.pk for sku in visible_skus}
    by_spu = defaultdict(list)
    for sku in visible_skus:
        by_spu[sku.spu_id].append(sku)

    inventory_allowed = check_user_permission(actor, cd.INVENTORY)
    records = []
    if inventory_allowed and visible_ids:
        source = cd._country_inventory_source(actor, country, now)
        # Select identities from all history, then rank ALL versions of those
        # identities. Do not filter by current mapping before ranking.
        aliases = list(source.filter(internal_sku_id__in=visible_ids).order_by()
            .values_list('source_sku', flat=True).distinct())
        ranked = latest_country_inventory(source.filter(source_sku__in=aliases))
        scoped = filter_inventory_queryset(actor, cd.INVENTORY, ranked)
        records = list(scoped.filter(internal_sku_id__in=visible_ids)
            .filter(warehouse__country_code__iexact=country.country_code)
            .select_related("source_run", "internal_sku").order_by())
    stock = _stock_by_sku_warehouse(records, now=now)

    listing = country_listing_evidence(actor, country.country_code, visible_skus)
    output = {}
    for spu_id, members in by_spu.items():
        physical = [sku for sku in members if sku.inventory_type != "virtual"]
        virtual = [sku for sku in members if sku.inventory_type == "virtual"]
        all_stock_rows = [stock.get(sku.pk) for sku in physical]
        known = inventory_allowed and bool(all_stock_rows) and all(
            row is not None and row["complete"] for row in all_stock_rows)
        qty = lambda key: sum((row[key] for row in all_stock_rows if row and row["complete"]), Decimal(0)) if known else None
        virtual_rows = [stock.get(sku.pk) for sku in virtual]
        virtual_known = inventory_allowed and bool(virtual_rows) and all(
            row is not None and row["complete"] for row in virtual_rows)
        states = [state for sku in members for state in listing.get(sku.pk, ())]
        has_mapping = any(listing.get(sku.pk) for sku in members)
        risk = classify_country_risk(on_hand_qty=qty("on_hand"), available_qty=qty("available"),
            in_transit_qty=qty("in_transit") or 0, pending_putaway_qty=qty("pending_putaway") or 0,
            inventory_known=known, listing_states=states, has_mapping=has_mapping)
        spu = members[0].spu
        output[spu_id] = {
            "spu_id": spu_id, "spu_code": spu.spu_code, "country_code": country.country_code,
            "scope": "authorized_scope", "scope_complete": None,
            "sku_count": len(members), "inventory_known": known,
            "on_hand_qty": qty("on_hand"), "available_qty": qty("available"),
            "in_transit_qty": qty("in_transit"), "pending_putaway_qty": qty("pending_putaway"),
            "virtual_inventory_known": virtual_known,
            "virtual_on_hand_qty": sum((r["virtual_on_hand"] for r in virtual_rows if r and r["complete"]), Decimal(0)) if virtual_known else None,
            "virtual_available_qty": sum((r["virtual_available"] for r in virtual_rows if r and r["complete"]), Decimal(0)) if virtual_known else None,
            "status": risk["code"], "label": risk["label"], "reasons": risk["reasons"],
            "complete": False,
            "inventory_issues": sorted({issue for r in all_stock_rows if r for issue in r["issues"]}),
        }
    return output
