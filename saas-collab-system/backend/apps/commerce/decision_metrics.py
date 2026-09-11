"""Observed facts, not inferred coverage. This module never writes business data."""
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .models import InventorySnapshot, RefundReturnItem, SalesOrderItem


POLICY_VERSION = "facts-utc-v1"


def collect_decision_metrics(*, tenant, sku, stores, warehouses, as_of=None):
    as_of = as_of or timezone.now()
    if timezone.is_naive(as_of):
        raise ValidationError("An aware evaluation timestamp is required.")
    if sku.tenant_id != tenant.id or not stores or not warehouses:
        raise ValidationError("A tenant SKU and explicit stores/warehouses are required.")
    if any(subject.tenant_id != tenant.id for subject in [*stores, *warehouses]):
        raise ValidationError("Decision subjects must belong to the same tenant.")
    store_ids = sorted({store.id for store in stores})
    warehouse_ids = sorted({warehouse.id for warehouse in warehouses})
    end = datetime.combine(as_of.astimezone(UTC).date(), time.min, tzinfo=UTC)
    all_lines = SalesOrderItem.objects.filter(
        sales_order__tenant=tenant, sales_order__store_id__in=store_ids,
        sales_order__created_at_utc__gte=end - timedelta(days=90),
        sales_order__created_at_utc__lt=end,
    )
    eligible = all_lines.filter(
        sales_order__normalized_status__in=["confirmed", "fulfilled", "completed"],
        sales_order__paid_at_utc__isnull=False,
        sales_order__paid_at_utc__lt=end,
        sales_order__source_run__tenant=tenant,
        sales_order__source_run__status="success",
        sales_order__source_run__failed_count=0,
    )
    lines = eligible.filter(internal_sku=sku)
    issues = []
    unmapped = eligible.filter(internal_sku__isnull=True).count()
    if unmapped:
        issues.append("unmapped_order_lines")
    if not lines.exists():
        issues.append("no_sales_facts")
    windows = []
    for days in (30, 60, 90):
        start = end - timedelta(days=days)
        selected = lines.filter(sales_order__created_at_utc__gte=start)
        units = selected.aggregate(total=Sum("quantity"))["total"] or 0
        refunds = RefundReturnItem.objects.filter(
            internal_sku=sku, refund_return__tenant=tenant,
            refund_return__store_id__in=store_ids,
            refund_return__requested_at_utc__gte=start, refund_return__requested_at_utc__lt=end,
        ).values("currency").annotate(amount=Sum("refund_amount"))
        windows.append({
            "days": days, "start_at": start.isoformat(), "end_at_exclusive": end.isoformat(),
            "observed_units": units, "observed_order_count": selected.values("sales_order_id").distinct().count(),
            "observed_daily_sales": str(Decimal(units) / days),
            "refund_amount_by_currency": {row["currency"]: str(row["amount"]) for row in refunds},
        })
    stock = []
    snapshot_ids = []
    for warehouse_id in warehouse_ids:
        # Pick latest per upstream identity before considering the internal mapping:
        # an unmapped newer snapshot must never fall back to a mapped older one.
        seen = set()
        selected = []
        for snapshot in InventorySnapshot.objects.filter(
            tenant=tenant, warehouse_id=warehouse_id, snapshot_at_utc__lte=as_of,
        ).select_related("source_run").order_by("-snapshot_at_utc", "-id"):
            identity = (snapshot.site_code, snapshot.source_sku)
            if identity in seen:
                continue
            seen.add(identity)
            if snapshot.internal_sku_id is None:
                issues.append("unmapped_inventory")
            if snapshot.internal_sku_id == sku.id:
                selected.append(snapshot)
        if not selected:
            issues.append("missing_warehouse_snapshot")
        if any(s.snapshot_at_utc < as_of - timedelta(hours=24) for s in selected):
            issues.append("stale_inventory_snapshot")
        if any(s.source_run.tenant_id != tenant.id or s.source_run.status != "success"
               or s.source_run.failed_count for s in selected):
            issues.append("inventory_source_run_incomplete")
        snapshot_ids.extend(s.id for s in selected)
        stock.append({"warehouse_id": warehouse_id,
                      "available_qty": sum(s.available_qty for s in selected),
                      "in_transit_qty": sum(s.in_transit_qty for s in selected)})
    # Existing successful runs do not prove a complete order-time window or full
    # inventory enumeration. Do not manufacture completeness from earliest rows,
    # current mutable job settings, or an empty cursor.
    issues.append("collection_coverage_unproven")
    return {
        "policy_version": POLICY_VERSION, "mode": "facts_preview", "evaluatable": False,
        "issues": sorted(set(issues)), "sku_id": sku.id, "store_ids": store_ids,
        "warehouse_ids": warehouse_ids, "windows": windows, "inventory": stock,
        "unmapped_order_lines": unmapped, "source_snapshot_ids": sorted(snapshot_ids),
        "source_run_ids": sorted(set(lines.values_list("sales_order__source_run_id", flat=True))),
        "notice": "观察值不等于完整需求；退款按币种单列，未扣减销量。不生成建议、预警或生命周期决策。",
    }
