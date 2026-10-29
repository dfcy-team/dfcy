"""Tenant-local creator countries and independently scoped operational records.

Creator countries come from explicitly granted, active warehouses. Platform
grants never authorize additional creator countries. Unknown markets fail closed.
"""
import re

from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p2_scopes import filter_master_data


COUNTRY_NAMES = {
    "PH": ("菲律宾", "Philippines"), "MY": ("马来西亚", "Malaysia"),
    "TH": ("泰国", "Thailand"), "VN": ("越南", "Vietnam"),
    "SG": ("新加坡", "Singapore"), "ID": ("印度尼西亚", "印尼", "Indonesia"),
    "CN": ("中国", "China"), "US": ("美国", "United States"),
    "GB": ("英国", "United Kingdom"), "JP": ("日本", "Japan"),
}
SEPARATORS = r"[,，、;/；|\s]+"


def _scopes(user, code):
    if not check_user_permission(user, code):
        return []
    return get_permission_data_scopes(user, code)


def has_all_scope(user, code):
    return any(s["scope_type"] == "all" for s in _scopes(user, code))


def authorized_warehouses(user, code):
    rows = WarehouseMaster.objects.filter(tenant_id=user.tenant_id, status="active")
    scopes = _scopes(user, code)
    if any(s["scope_type"] == "all" for s in scopes):
        return rows
    # Do not infer warehouses from platform grants: countries are an explicit
    # warehouse authorization, not all countries served by a platform.
    ids = {v for s in scopes if s["scope_type"] == "custom"
           for v in (s.get("config") or {}).get("warehouse_ids", [])
           if type(v) is int and v > 0}
    return rows.filter(pk__in=ids)


def allowed_countries(user, code):
    if has_all_scope(user, code):
        return None
    return frozenset(str(c).strip().upper() for c in
                     authorized_warehouses(user, code).values_list("country_code", flat=True) if c)


def require_scope(user, code):
    if allowed_countries(user, code) == frozenset():
        raise PermissionDenied("当前权限未配置有效仓库国家范围，请联系管理员。")


def market_countries(value):
    aliases = {alias.casefold(): code for code, names in COUNTRY_NAMES.items()
               for alias in (code, *names)}
    # Replace known multi-word country names before splitting.
    text = str(value or "").strip()
    for code, names in COUNTRY_NAMES.items():
        for alias in names:
            text = re.sub(re.escape(alias), code, text, flags=re.IGNORECASE)
    parts = [p for p in re.split(SEPARATORS, text) if p]
    return frozenset(aliases.get(p.casefold(), p.upper()) for p in parts)


def market_filter(countries):
    query = Q(pk__in=[])
    for code in countries:
        names = (code, *COUNTRY_NAMES.get(code, ()))
        pattern = r"(^|[,，、;/；|\s])(" + "|".join(re.escape(v) for v in names) + r")($|[,，、;/；|\s])"
        query |= Q(profile__market__iregex=pattern)
    return query


def filter_queryset(user, queryset, code):
    from .models import Influencer, OutreachTask, OutreachTarget, SampleFulfillment, SampleItem, SkuPriceSnapshot
    queryset = queryset.all().filter(tenant_id=user.tenant_id)
    countries = allowed_countries(user, code)
    if countries is None:
        return queryset
    if not countries:
        return queryset.none()
    model = queryset.model
    if model is Influencer:
        return queryset.filter(profile__tenant_id=user.tenant_id).filter(market_filter(countries))
    if model is WarehouseMaster:
        return queryset.filter(pk__in=authorized_warehouses(user, code).values("pk"))
    stores = filter_master_data(user, StoreMaster.objects.filter(tenant_id=user.tenant_id), code, "stores")
    stores = stores.filter(country_code__in=countries)
    if model is StoreMaster:
        return queryset.filter(pk__in=stores.values("pk"))
    if model is OutreachTask:
        return queryset.filter(store_id__in=stores.values("pk"))
    if model is OutreachTarget:
        tasks = filter_queryset(user, OutreachTask.objects.all(), code)
        creators = filter_queryset(user, Influencer.objects.all(), code)
        return queryset.filter(task_id__in=tasks.values("pk"), influencer_id__in=creators.values("pk"))
    if model is SampleFulfillment:
        # Null warehouse legacy items stay visible under their authorized store;
        # an explicitly assigned foreign/unauthorized warehouse hides the record.
        forbidden = SampleItem.objects.filter(fulfillment_id=OuterRef("pk")).exclude(
            Q(warehouse_id__isnull=True) | Q(warehouse_id__in=authorized_warehouses(user, code).values("pk"))
        )
        return queryset.filter(store_id__in=stores.values("pk")).alias(
            _scope_forbidden_warehouse=Exists(forbidden)
        ).filter(_scope_forbidden_warehouse=False)
    if model is SkuPriceSnapshot:
        return queryset.filter(listing__tenant_id=user.tenant_id, listing__store_id__in=stores.values("pk"))
    raise PermissionDenied("该资源尚未支持受限数据范围。")


def require_object(user, obj, code):
    if obj is None or not filter_queryset(user, type(obj).objects.filter(pk=obj.pk), code).exists():
        raise PermissionDenied("该记录不在当前授权国家、店铺或仓库范围内。")


def filter_any_permission(user, queryset, codes):
    """Union independent grants without combining their warehouse/store parts.

    Build scope subqueries from the model, not the caller's correlated queryset:
    resolve status annotations use OuterRef against the enclosing creator row.
    """
    allowed = Q(pk__in=[])
    for code in codes:
        permitted = filter_queryset(user, queryset.model.objects.all(), code)
        allowed |= Q(pk__in=permitted.values("pk"))
    return queryset.filter(tenant_id=user.tenant_id).filter(allowed)


def validate_market(user, payload, code, *, instance=None):
    countries = allowed_countries(user, code)
    if countries is None:
        return
    if instance is not None:
        require_object(user, instance, code)
    profile = payload.get("profile")
    if instance is not None and (not isinstance(profile, dict) or "market" not in profile):
        return
    requested = market_countries(profile.get("market") if isinstance(profile, dict) else "")
    if not requested or not requested.issubset(countries):
        raise ValidationError({"profile": {"market": "请选择已授权仓库所属国家；国家不能为空或超出范围。"}})


def validate_relations(user, data, code):
    """Run after serializer validation, before any write or idempotent replay."""
    for field in ("store", "influencer", "outreach_task", "outreach_target", "task"):
        obj = data.get(field)
        if obj is not None:
            if obj.tenant_id != user.tenant_id:
                raise ValidationError({field: "关联记录必须属于当前租户。"})
            require_object(user, obj, code)
    for field in ("items", "append_items"):
        for item in data.get(field) or []:
            if item.get("warehouse") is not None:
                require_object(user, item["warehouse"], code)
