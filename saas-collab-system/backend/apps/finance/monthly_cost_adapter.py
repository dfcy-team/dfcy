"""Opt-in monthly finance lookup; no writes and no silent legacy fallback after cutover."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from django.conf import settings
from apps.products.monthly_cost_models import MonthlyProductCost


def monthly_cost_index(tenant):
    if getattr(settings, "MONTHLY_PRODUCT_COST_FINANCE_ENABLED", False) is not True:
        return None
    cutover = getattr(settings, "MONTHLY_PRODUCT_COST_CUTOVER_MONTH", "")
    try:
        parsed = date.fromisoformat(cutover + "-01")
    except ValueError:
        raise ValueError("MONTHLY_PRODUCT_COST_CUTOVER_MONTH must be YYYY-MM before finance activation")
    rows=MonthlyProductCost.objects.filter(tenant=tenant,month__gte=parsed).select_related("warehouse")
    return {"cutover":cutover,"rows":{(r.sku_id,r.warehouse_id,r.month.isoformat()[:7]):r for r in rows}}


def select_monthly_cost(index, sku_id, warehouse_id, day, legacy=None):
    if index is None or day[:7] < index["cutover"]:
        return legacy
    row=index["rows"].get((sku_id,warehouse_id,day[:7]))
    if row is None or not row.is_complete or row.unit_cost is None:
        return None
    return SimpleNamespace(pk=None,version_no=row.version_no,confirmed_cost=row.unit_cost,currency="CNY",
        effective_from=datetime(row.month.year,row.month.month,1,tzinfo=timezone.utc),effective_to=None,
        monthly_cost_id=row.pk,monthly_cost_status=row.status,monthly_cost_month=day[:7])
