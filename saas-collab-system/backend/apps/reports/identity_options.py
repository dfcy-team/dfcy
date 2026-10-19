"""Bounded identity choices derived from the caller's authorized report facts."""
from types import SimpleNamespace

from django.db.models import Exists, OuterRef, Q
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from apps.masterdata.models import StoreMaster
from .datasets import DATASETS, normalize_config, selected_permission, source_queryset


def store_options(request, payload):
    if not isinstance(payload, dict) or set(payload) - {"dataset", "search"}:
        raise ValidationError("店铺筛选参数格式不正确。")
    name = payload.get("dataset")
    if not isinstance(name, str) or name not in {"sales", "sales_skus", "refunds", "finance", "advertising"}:
        raise ValidationError("当前报表不支持店铺筛选。")
    search = payload.get("search", "")
    if not isinstance(search, str) or len(search) > 100:
        raise ValidationError("店铺搜索最多100个字符。")
    dataset = DATASETS[name]
    permission = selected_permission(request.user, dataset)
    if name == "advertising":
        from apps.integrations.models import ShopeeAdvertisingRecord
        from apps.permissions.ui_p6_scopes import filter_analytics_queryset
        # Choices describe authorized identities, not a fixed recent period.
        # Keep the same shop_daily and analytics gates as advertising_queryset.
        facts = filter_analytics_queryset(request.user, ShopeeAdvertisingRecord.objects.filter(
            tenant=request.user.tenant, kind="shop_daily"
        ), permission)
    else:
        config = normalize_config({"dataset": name, **dataset["defaults"], "filters": {}})
        facts = source_queryset(SimpleNamespace(user=request.user, query_params=QueryDict()), config, permission)
    store_field = "sales_order__store_id" if name == "sales_skus" else "store_id"
    stores = StoreMaster.objects.filter(tenant=request.user.tenant).filter(
        Exists(facts.filter(**{store_field: OuterRef("pk")}))
    )
    search = search.strip()
    if search:
        match = Q(name__icontains=search) | Q(code__icontains=search)
        if search.isdecimal() and len(search) <= 18:
            match |= Q(pk=int(search))
        stores = stores.filter(match)
    rows = list(stores.order_by("name", "pk").values(
        "pk", "name", "code", "country_code", "platform__platform_type"
    )[:101])
    return {"options": [{"value": str(row["pk"]), "label": " · ".join(filter(None, (
        row["name"] or "店铺名称未维护", row["platform__platform_type"], row["country_code"],
        row["code"], f'ID {row["pk"]}',
    )))} for row in rows[:100]], "has_more": len(rows) > 100}
