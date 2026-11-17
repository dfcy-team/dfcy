"""Permission-scoped sales SKU archive issues for the replenishment reference."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _issue_row(row, *, reason):
    sku = row.get("seller_sku") or "（空 SKU）"
    missing_link = reason == "missing_internal_sku"
    return {
        "seller_sku": sku,
        "store_id": row["sales_order__store_id"],
        "store_name": row["sales_order__store__name"],
        "platform_product_id": row["platform_product_id"],
        "platform_variant_id": row["platform_variant_id"],
        "line_count": row["line_count"],
        "units": row["units"],
        "reason": reason,
        "code": "unmapped_sales_sku" if missing_link else "bundle_archive_missing",
        "message": (f"销售 SKU 未关联内部商品：{sku}" if missing_link
                    else f"组合商品（商品SKU）没有档案：{sku}"),
    }


def sales_archive_issues(*, actor, country, end_date, window_days=30, offset=0, limit=20, platform_type=None):
    """List unresolved effective sales rows in authorized stores; never infer a SKU.

    ``end_date`` is inclusive in each store's local calendar. The result total is
    exact; rows are grouped and paginated, so the caller can expose more pages.
    """
    from django.db.models import Count, Q, Sum
    from apps.commerce.models import SalesOrderItem
    from apps.commerce.country_decisions import SALES
    from apps.permissions.services import check_user_permission
    from apps.sales_management.scopes import filter_sales_queryset
    from apps.masterdata.models import StoreMaster

    if type(window_days) is not int or not 1 <= window_days <= 366:
        raise ValueError("window_days must be between 1 and 366")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid pagination")
    if not end_date:
        raise ValueError("end_date is required")
    if not actor or actor.tenant_id is None:
        return {"title": "组合商品（商品SKU）没有档案", "total": 0, "offset": offset,
                "limit": limit, "rows": [], "coverage": "unknown"}
    if not check_user_permission(actor, SALES):
        return {"title": "组合商品（商品SKU）没有档案", "total": 0, "offset": offset,
                "limit": limit, "rows": [], "coverage": "unauthorized"}

    stores = filter_sales_queryset(actor, SALES, StoreMaster.objects.filter(
        tenant_id=actor.tenant_id, country_code__iexact=country.country_code,
        status="active", platform__status="active"),
        {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"})
    if platform_type:
        stores = stores.filter(platform__platform_type__iexact=platform_type)
    from django.db.models import Case, When, Value, CharField
    bounds = Q(pk__in=[])
    invalid_timezones = 0
    for store in stores.only("id", "name", "timezone").iterator():
        try:
            zone = ZoneInfo(store.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            invalid_timezones += 1
            continue
        start = end_date - timedelta(days=window_days - 1)
        lower = datetime.combine(start, time.min, tzinfo=zone)
        upper = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
        bounds |= Q(sales_order__store_id=store.pk, sales_order__created_at_utc__gte=lower,
                    sales_order__created_at_utc__lt=upper, sales_order__paid_at_utc__lt=upper)
    eligible = SalesOrderItem.objects.filter(bounds, sales_order__tenant_id=actor.tenant_id,
        sales_order__paid_at_utc__isnull=False,
        sales_order__normalized_status__in=["confirmed", "fulfilled", "completed"],
        sales_order__source_run__status="success", sales_order__source_run__failed_count=0)
    grouped = eligible.filter(Q(internal_sku__isnull=True) | Q(internal_sku__product_type="bundle", bundle_snapshot__isnull=True)).annotate(
        archive_reason=Case(When(internal_sku__isnull=True, then=Value("missing_internal_sku")),
            default=Value("missing_bundle_snapshot"), output_field=CharField())).values(
        "seller_sku", "sales_order__store_id", "sales_order__store__name", "platform_product_id", "platform_variant_id", "archive_reason").annotate(
        line_count=Count("pk"), units=Sum("quantity")).order_by("seller_sku", "sales_order__store_id", "platform_product_id", "platform_variant_id", "archive_reason")
    total = grouped.count()
    results = [_issue_row(row, reason=row["archive_reason"]) for row in grouped[offset:offset+limit]]
    return {"title": "组合商品（商品SKU）没有档案", "total": total,
        "offset": offset, "limit": limit, "rows": results,
        "coverage": "partial" if invalid_timezones else "authorized_active_stores",
        "invalid_timezone_stores": invalid_timezones, "end_date": str(end_date), "window_days": window_days}
