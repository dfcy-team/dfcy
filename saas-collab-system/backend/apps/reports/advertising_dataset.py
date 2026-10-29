"""Aggregate the safe, shop-level Shopee advertising daily facts."""
from datetime import date
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, Sum, Value, When
from django.db.models.functions import Cast
from rest_framework.exceptions import ValidationError

from apps.integrations.models import ShopeeAdvertisingRecord
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.models import DataScope
from apps.permissions.resource_policies import validate_resource_policy


def _field(label, source, kind="dimension", definition=""):
    return {"label": label, "source": source, "kind": kind, "definition": definition}


_NUMERIC_RE = r"^[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
_NUMBER = DecimalField(max_digits=38, decimal_places=12)


def _metric(key):
    """Return NULL for absent or malformed provider values, never a fake zero."""
    return Case(
        When(**{f"data__{key}__regex": _NUMERIC_RE}, then=Cast(F(f"data__{key}"), _NUMBER)),
        default=Value(None, output_field=_NUMBER),
        output_field=_NUMBER,
    )


def _observed_sum(key):
    # Sum valid observations; SQL keeps an entirely missing metric NULL.
    return Sum(_metric(key))


ADVERTISING_DATASET = {
    "name": "Shopee 广告日报",
    "module": "经营分析",
    "permissions": ["analytics.view"],
    "report_type": "analytics_summary",
    "path": "/analytics/advertising-overview",
    "dimensions": {
        "date": _field("报表日期", "report_date"),
        "report_date": _field("报表日期", "report_date"),
        "currency": _field("币种", "currency"),
        "store_id": _field("店铺", "store_id"),
        "country": _field("国家代码", "store__country_code"),
        "storecountry": _field("店铺国家", "store__country_code"),
        "platform": _field("平台", Value("shopee")),
    },
    "metrics": {
        "expense": _field("广告消耗", _observed_sum("expense"), "money", "已拉取的有效消耗暂估，不等于账单扣费。"),
        "impressions": _field("展示量", _observed_sum("impression"), "count"),
        "clicks": _field("点击量", _observed_sum("clicks"), "count"),
        "direct_gmv": _field("直接归因 GMV", _observed_sum("direct_gmv"), "money", "仅直接归因；不可与广泛归因相加。"),
        "broad_gmv": _field("广泛归因 GMV", _observed_sum("broad_gmv"), "money", "仅广泛归因；不可与直接归因相加。"),
        "record_count": _field("日报记录数", Count("pk"), "count"),
    },
    "defaults": {
        "dimensions": ["date", "store_id", "currency"],
        "metrics": ["expense", "impressions", "clicks", "direct_gmv", "broad_gmv", "record_count"],
    },
    "note": "按目前已拉取的有效指标暂估；部分数据可能尚未拉取或字段缺失，后续同步可能调整。完全缺失的指标留空，不作为零。仅聚合店铺级日报；不会混合小时、活动或周期数据。币种必须分组。Shopee 归因窗口为 7 天，最近 7 天数据可能回补。直接与广泛归因 GMV 分开呈现，不能相加。",
}

ADVERTISING_FILTERS = ["date_from", "date_to", "currency", "store_id", "store_ids", "country", "storecountry", "region", "platform", "platforms"]
# Self-service comparisons may fetch the current and prior year in one query.
MAX_DATE_SPAN_DAYS = 732


def _filter_values(value, name, *, integers=False):
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    values = [str(item).strip() for item in values]
    if not values or len(values) > 100 or any(not item for item in values):
        raise ValidationError(f"{name} 必须包含 1 至 100 个非空值。")
    if integers:
        if any(not item.isascii() or not item.isdigit() or len(item) > 19 or not 0 < int(item) <= 9223372036854775807 for item in values):
            raise ValidationError(f"{name} 必须是有效的正整数店铺编号。")
        return [int(item) for item in values]
    return [item.lower() for item in values]


def filter_advertising_dimensions(queryset, filters):
    """Intersect explicit filters inside the caller's existing tenant/scope gate."""
    for key in ("platform", "platforms"):
        if filters.get(key) and "shopee" not in _filter_values(filters[key], key):
            return queryset.none()
    if filters.get("store_id"):
        values = _filter_values(filters["store_id"], "store_id", integers=True)
        if len(values) != 1:
            raise ValidationError("store_id 只能包含一个店铺编号。")
        queryset = queryset.filter(store_id=values[0])
    if filters.get("store_ids"):
        queryset = queryset.filter(store_id__in=_filter_values(filters["store_ids"], "store_ids", integers=True))
    if filters.get("currency"):
        queryset = queryset.filter(currency=filters["currency"])
    for key in ("country", "storecountry", "region"):
        if filters.get(key):
            queryset = queryset.filter(store__country_code=str(filters[key]).strip().upper())
    return queryset


def _advertising_scope_branches(user):
    """Resolve resource overrides per granting role; never discard restrictions."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from rest_framework.exceptions import PermissionDenied
    from apps.common.exceptions import DataScopeDenied
    from apps.common.error_codes import ErrorCode

    def invalid(message):
        raise DataScopeDenied(message, error_code=ErrorCode.DATA_SCOPE_INVALID)

    if not check_user_permission(user, "analytics.view"):
        raise PermissionDenied("当前用户没有经营分析查看权限。")
    scopes = get_permission_data_scopes(user, "analytics.view", resource_code="analytics.advertising")
    branches = []
    for scope in scopes:
        config = scope.get("config") or {}
        if scope.get("source") == "resource_policy":
            try:
                config = validate_resource_policy(user.tenant_id, "analytics.advertising", scope["scope_type"], config)
            except DjangoValidationError:
                invalid("广告数据范围配置无效，请管理员核对平台、站点和店铺授权。")
            branches.append(("all" if scope["scope_type"] == DataScope.ScopeType.ALL else "identity", config))
            continue
        if scope["scope_type"] == DataScope.ScopeType.ALL:
            branches.append(("all", {}))
            continue
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            raise DataScopeDenied("广告不支持此数据范围类型。", error_code=ErrorCode.DATA_SCOPE_UNSUPPORTED)
        if not isinstance(config, dict):
            invalid("广告数据范围配置必须是对象。")
        if set(config) - ({"analytics_dimensions"} | set(DataScope.BUSINESS_SCOPE_KEYS)):
            invalid("广告数据范围包含未知字段。")
        if set(config) & (set(DataScope.BUSINESS_SCOPE_KEYS) - {"analytics_dimensions"}):
            continue
        dimensions = config.get("analytics_dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            invalid("广告分析维度范围必须为非空数组。")
        for item in dimensions:
            if not isinstance(item, dict) or not item or set(item) - {"platform", "store_id", "country", "product_id", "sku_id", "warehouse_id"}:
                invalid("广告分析维度范围无效。")
            if any(not isinstance(item[key], str) or not item[key].strip() for key in set(item) & {"platform", "store_id", "country"}):
                invalid("广告分析维度标识无效。")
            if any(type(item[key]) is not int or item[key] < 1 for key in set(item) & {"product_id", "sku_id", "warehouse_id"}):
                invalid("广告分析维度编号无效。")
            branches.append(("legacy", item))
    if not branches:
        raise DataScopeDenied(
            "当前数据范围无法应用到广告，请管理员配置广告数据专用范围；原仓库限制仍保留。",
            error_code=ErrorCode.DATA_SCOPE_UNSUPPORTED,
        )
    return branches


def _identity_condition(user, config, *, stores):
    from django.db.models import Q
    from apps.masterdata.models import CountrySiteMaster
    prefix = "" if stores else "store__"
    condition = Q()
    if "platform_ids" in config:
        condition &= Q(**{prefix + "platform_id__in": config["platform_ids"]})
    if "site_ids" in config:
        countries = CountrySiteMaster.objects.filter(
            tenant_id=user.tenant_id, pk__in=config["site_ids"]
        ).values("country_code")
        condition &= Q(**{prefix + "country_code__in": countries})
    if "store_ids" in config:
        condition &= Q(**{("pk__in" if stores else "store_id__in"): config["store_ids"]})
    return condition


def apply_advertising_scopes(user, queryset):
    """Apply the same role branches to facts, preserving legacy JSON predicates."""
    from django.db.models import Q
    queryset = queryset.filter(tenant_id=user.tenant_id, store__tenant_id=user.tenant_id)
    allowed = Q(pk__in=[])
    branches = _advertising_scope_branches(user)
    if any(kind == "all" for kind, _ in branches):
        return queryset
    for kind, config in branches:
        if kind == "identity":
            allowed |= _identity_condition(user, config, stores=False)
        else:
            allowed |= Q(**{f"dimensions__{key}": value for key, value in config.items()})
    return queryset.filter(allowed)


def filter_advertising_stores(user, queryset):
    """Authorize identities independently of whether advertising was collected."""
    from django.db.models import Q
    from django.db.models.functions import Cast
    from django.db.models import CharField
    queryset = queryset.filter(tenant_id=user.tenant_id).annotate(_ad_store_key=Cast("pk", CharField()))
    branches = _advertising_scope_branches(user)
    if any(kind == "all" for kind, _ in branches):
        return queryset
    allowed = Q(pk__in=[])
    names = {"platform": "platform__platform_type", "store_id": "_ad_store_key", "country": "country_code"}
    for kind, config in branches:
        if kind == "identity":
            allowed |= _identity_condition(user, config, stores=True)
        elif set(config) <= set(names):
            allowed |= Q(**{names[key]: value for key, value in config.items()})
    return queryset.filter(allowed)


def advertising_queryset(request, filters, permission):
    """Return a tenant and analytics-scope restricted shop_daily queryset."""
    if permission != "analytics.view":
        raise ValidationError("Shopee 广告日报仅支持 analytics.view 权限。")
    start_raw, end_raw = filters.get("date_from"), filters.get("date_to")
    if not start_raw or not end_raw:
        raise ValidationError("广告日报查询必须同时提供开始和结束日期。")
    try:
        start = start_raw if isinstance(start_raw, date) else date.fromisoformat(str(start_raw))
        end = end_raw if isinstance(end_raw, date) else date.fromisoformat(str(end_raw))
    except (TypeError, ValueError) as exc:
        raise ValidationError("广告日报日期格式应为 YYYY-MM-DD。") from exc
    if start > end:
        raise ValidationError("开始日期不能晚于结束日期。")
    if (end - start).days + 1 > MAX_DATE_SPAN_DAYS:
        raise ValidationError(f"广告日报日期范围最多为 {MAX_DATE_SPAN_DAYS} 天。")

    queryset = ShopeeAdvertisingRecord.objects.filter(
        tenant=request.user.tenant,
        store__tenant=request.user.tenant,
        kind="shop_daily",
        report_date__gte=start,
        report_date__lte=end,
    )
    # Resource overrides replace only the corresponding role scope; old roles
    # retain their complete fact-level dimension predicates.
    queryset = apply_advertising_scopes(request.user, queryset)
    return filter_advertising_dimensions(queryset, filters).order_by()
