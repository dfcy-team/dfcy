"""Provisional shop-level ROI from currently stored advertising facts."""
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.db import DatabaseError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.reports.advertising_dataset import advertising_queryset


_NUMBER_RE = r"^[+]?(?:[0-9]{1,26}(?:\.[0-9]{0,12})?|\.[0-9]{1,12})$"
_DECIMAL = DecimalField(max_digits=38, decimal_places=12)
_PROVISIONAL = "数据拉取不全，按已入库数据计算（暂估）"


def _valid_expense():
    return Case(
        When(data__expense__regex=_NUMBER_RE, then=Cast(KeyTextTransform("expense", "data"), _DECIMAL)),
        default=Value(None, output_field=_DECIMAL),
        output_field=_DECIMAL,
    )


def _ratio(gmv, expense):
    if gmv is None or expense is None:
        return None
    spend = Decimal(expense)
    if not spend.is_finite() or spend <= 0:
        return None
    value = Decimal(gmv) / spend
    return str(value.normalize())


def _amount(value):
    if value is None:
        return None
    rendered = format(Decimal(value).normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def shop_roi_fields(request, sales_orders, params):
    """Return (store,currency) fields from an analytics and sales scope intersection."""
    from apps.permissions.services import check_user_permission

    if not check_user_permission(
        request.user, "analytics.view", cache=getattr(request, "_permission_resolution_cache", None),
    ):
        return {}, "暂无广告数据查看权限。"

    store_ids = sales_orders.order_by().values("store_id").distinct()
    filters = {
        "date_from": params["previous_from"], "date_to": params["date_to"],
    }
    if params["currency"]:
        filters["currency"] = params["currency"]
    data = {}
    try:
        # Keep a broken or temporarily unavailable ad source from suppressing
        # sales rows; the savepoint lets callers continue inside transactions.
        with transaction.atomic():
            ads = advertising_queryset(request, filters, "analytics.view").filter(store_id__in=store_ids)
            metric = _valid_expense()
            for row in ads.values("store_id", "currency").annotate(
                current=Sum(metric, filter=Q(
                    report_date__gte=params["date_from"], report_date__lte=params["date_to"],
                )),
                previous=Sum(metric, filter=Q(
                    report_date__gte=params["previous_from"], report_date__lte=params["previous_to"],
                )),
            ):
                data[(row["store_id"], row["currency"])] = (row["current"], row["previous"])
    except PermissionDenied:
        return {}, "暂无当前广告数据范围查看权限，无法计算 ROI。"
    except (DatabaseError, ValidationError):
        return {}, "广告数据暂不可用，无法计算 ROI。"
    return data, None


def roi_values(gmv, previous_gmv, expenses):
    """Format shop ROI values and a truthful provisional/missing-data reason."""
    current_spend, previous_spend = expenses
    if current_spend is None:
        return None, None, None, "当前周期暂无有效店铺广告费记录，无法计算 ROI。"
    if gmv is None:
        return _amount(current_spend), None, None, "当前周期暂无可比 GMV，无法计算 ROI。"
    roi = _ratio(gmv, current_spend)
    previous_roi = _ratio(previous_gmv, previous_spend)
    delta = None if roi is None or previous_roi is None else str(Decimal(roi) - Decimal(previous_roi))
    if roi is None:
        return _amount(current_spend), None, None, "当前周期广告费为 0，无法计算 ROI。"
    return _amount(current_spend), roi, delta, _PROVISIONAL
