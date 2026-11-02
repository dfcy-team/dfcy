"""Aggregate the safe, shop-level Shopee advertising daily facts."""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Cast
from rest_framework.exceptions import ValidationError

from apps.integrations.models import ShopeeAdvertisingRecord
from apps.permissions.services import check_user_permission
from apps.permissions.models import DataScope
from apps.permissions.resource_policies import validate_resource_policy
from apps.permissions.resource_policies import active_bindings


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


def advertising_store_scope(user):
    """Return tenant store IDs, preferring current operator or leader assignments."""
    from apps.masterdata.models import StoreMaster
    from apps.permissions.models import RoleResourcePolicy
    # Preserve the established tenant-local administrator ALL scope.
    if user.is_superuser:
        return "superuser", sorted(StoreMaster.objects.filter(tenant_id=user.tenant_id).values_list("pk", flat=True))
    assigned = set(StoreMaster.objects.filter(tenant_id=user.tenant_id).filter(
        Q(operator_id=user.pk) | Q(leader_id=user.pk)
    ).values_list("pk", flat=True))
    if assigned:
        ids = set(StoreMaster.objects.filter(tenant_id=user.tenant_id, pk__in=assigned).values_list("pk", flat=True))
        return "assigned", sorted(ids)

    role_ids = list(active_bindings(user).values_list("role_id", flat=True))
    if not role_ids:
        return "roles", []
    allowed, all_stores = set(), False
    policies = {}
    for row in RoleResourcePolicy.objects.filter(tenant_id=user.tenant_id, role_id__in=role_ids,
        resource_code="masterdata.stores", permission_code__in=["*", "masterdata.stores.view"]):
        if row.role_id not in policies or row.permission_code != "*":
            policies[row.role_id] = row
    role_scopes = DataScope.objects.filter(tenant_id=user.tenant_id, role_id__in=role_ids).values(
        "role_id", "scope_type", "config"
    )
    scopes_by_role = {}
    for row in role_scopes:
        scopes_by_role.setdefault(row["role_id"], []).append(row)
    for role_id in role_ids:
        policy = policies.get(role_id)
        scopes = ([{"source": "resource_policy", "scope_type": policy.scope_type, "config": policy.config}]
                  if policy else scopes_by_role.get(role_id, []))
        for scope in scopes:
            config = scope.get("config") or {}
            if scope.get("source") == "resource_policy":
                try:
                    config = validate_resource_policy(user.tenant_id, "masterdata.stores", scope["scope_type"], config)
                except (DjangoValidationError, KeyError, TypeError, ValueError) as exc:
                    from apps.common.exceptions import DataScopeDenied
                    raise DataScopeDenied("Invalid store authorization configuration.") from exc
                if config == {"all": True}:
                    all_stores = True
                else:
                    allowed.update(config.get("store_ids", []))
            elif scope.get("scope_type") == DataScope.ScopeType.ALL and config in ({}, {"all": True}):
                all_stores = True
            elif scope.get("scope_type") == DataScope.ScopeType.CUSTOM and isinstance(config, dict):
                if "store_ids" not in config:
                    continue
                values = config.get("store_ids", [])
                if not isinstance(values, list) or not values or any(type(value) is not int or value < 1 for value in values):
                    from apps.common.exceptions import DataScopeDenied
                    raise DataScopeDenied("Invalid store data scope configuration.")
                allowed.update(values)
    stores = StoreMaster.objects.filter(tenant_id=user.tenant_id)
    ids = sorted(stores.values_list("pk", flat=True)) if all_stores else sorted(stores.filter(pk__in=allowed).values_list("pk", flat=True))
    return "roles", ids


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


def apply_advertising_scopes(user, queryset):
    """Apply the resolved assigned-or-role Shopee store boundary to facts."""
    queryset = queryset.filter(tenant_id=user.tenant_id, store__tenant_id=user.tenant_id)
    if not check_user_permission(user, "analytics.view"):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("当前用户没有经营分析查看权限。")
    _, ids = advertising_store_scope(user)
    return queryset.filter(store_id__in=ids)


def filter_advertising_stores(user, queryset):
    """Authorize identities independently of whether advertising was collected."""
    queryset = queryset.filter(tenant_id=user.tenant_id)
    if not check_user_permission(user, "analytics.view"):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("当前用户没有经营分析查看权限。")
    _, ids = advertising_store_scope(user)
    return queryset.filter(pk__in=ids)


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
