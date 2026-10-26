"""Attach provisional ROI using already authorized observed advertising facts."""
from decimal import Decimal

from django.db.models import Count, F, Q, Sum

from apps.sales_management.observed_roi import roi_values
from apps.sales_management.views import _decimal_string


_ZERO = Decimal("0")
_COUNTRY_CONFLICT = "订单国家与店铺国家冲突，无法计算 ROI。"
_AGGREGATE_SCOPE = "；汇总ROI仅采用已有广告费的店铺GMV，不等于全部店铺GMV除以部分广告费。"
_OBSERVED_SCOPE = " 仅统计同店铺、同币种具有广告观测值的销售范围。"


def attach_operations_advertising(request, params, orders, period, previous, groups, rows,
                                  ad_expenses, ad_permission_reason):
    """Attach ROI without repeating the scoped advertising query or restricting sales."""
    if params["view"] != "stores":
        return

    current_sales = period & ~Q(normalized_status="cancelled")
    previous_sales = previous & ~Q(normalized_status="cancelled")
    conflict = ~Q(region="") & ~Q(region__iexact=F("store__country_code"))
    sales_by_pair = {
        (item["store_id"], item["currency"]): item
        for item in orders.order_by().values("store_id", "currency").annotate(
            current=Sum("order_total_amount", filter=current_sales),
            previous=Sum("order_total_amount", filter=previous_sales),
            current_conflicts=Count("pk", filter=current_sales & conflict),
            previous_conflicts=Count("pk", filter=previous_sales & conflict),
        )
    }

    # A country-conflict store/currency pair is excluded wholly from ROI, even
    # when it has advertising facts; ordinary sales totals remain untouched.
    valid_expenses = {
        key: expense for key, expense in ad_expenses.items()
        if key in sales_by_pair
        and not sales_by_pair[key]["current_conflicts"]
        and not sales_by_pair[key]["previous_conflicts"]
    }

    totals = {}
    for (store_id, currency), (current_spend, previous_spend) in valid_expenses.items():
        sale = sales_by_pair[(store_id, currency)]
        total = totals.setdefault(currency, {
            "current_spend": [], "previous_spend": [],
            "current_gmv": _ZERO, "previous_gmv": _ZERO,
            "has_current_gmv": False, "has_previous_gmv": False,
        })
        if current_spend is not None and sale["current"] is not None:
            total["current_spend"].append(current_spend)
            if current_spend > 0:
                total["current_gmv"] += Decimal(sale["current"])
                total["has_current_gmv"] = True
        if previous_spend is not None and sale["previous"] is not None:
            total["previous_spend"].append(previous_spend)
            if previous_spend > 0:
                total["previous_gmv"] += Decimal(sale["previous"])
                total["has_previous_gmv"] = True

    def expenses_for(currency):
        total = totals.get(currency)
        if not total or not total["current_spend"]:
            return None, None
        return (
            sum(total["current_spend"], _ZERO),
            sum(total["previous_spend"], _ZERO) if total["previous_spend"] else None,
        )

    def apply(target, current, old, expenses, *, aggregate=False, conflict_pair=False):
        if ad_permission_reason:
            target.update(ad_spend=None, roi=None, roi_delta=None, ad_sales_amount=None,
                          ad_status="unavailable", ad_reason=ad_permission_reason)
            return
        if conflict_pair:
            target.update(ad_spend=None, roi=None, roi_delta=None, ad_sales_amount=None,
                          ad_status="unavailable", ad_reason=_COUNTRY_CONFLICT)
            return
        spend, roi, roi_delta, reason = roi_values(current, old, expenses)
        # Zero-expense shops intentionally contribute no ROI numerator; that
        # does not mean the underlying sales observations are missing.
        if aggregate and expenses[0] == _ZERO:
            reason = "当前周期广告费为 0，无法计算 ROI。"
        target.update(ad_spend=spend,
                      roi=None if roi is None else _decimal_string(Decimal(roi)),
                      roi_delta=None if roi_delta is None else _decimal_string(Decimal(roi_delta)),
                      ad_status="provisional" if expenses[0] is not None else "unavailable",
                      ad_reason=reason)
        target["ad_sales_amount"] = _decimal_string(current) if current is not None and expenses[0] is not None and expenses[0] > 0 else None
        if aggregate:
            if roi is not None:
                target["ad_reason"] += _AGGREGATE_SCOPE + _OBSERVED_SCOPE
            if current is not None and expenses[0] is not None:
                target["ad_sales_amount"] = _decimal_string(current)

    for group in groups:
        currency = group["currency"]
        total = totals.get(currency)
        current = total["current_gmv"] if total and total["has_current_gmv"] else None
        old = total["previous_gmv"] if total and total["has_previous_gmv"] else None
        apply(group, current, old, expenses_for(currency), aggregate=True)

    for row in rows:
        key = (row["store_id"], row["currency"])
        sale = sales_by_pair.get(key)
        has_conflict = bool(sale and (sale["current_conflicts"] or sale["previous_conflicts"]))
        apply(row, sale["current"] if sale else None, sale["previous"] if sale else None,
              valid_expenses.get(key, (None, None)), conflict_pair=has_conflict)
