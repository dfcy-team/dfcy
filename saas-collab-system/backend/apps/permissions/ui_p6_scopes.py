import re

from django.db.models import F, Q, Subquery

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied

from .models import DataScope
from .services import get_permission_data_scopes


def _invalid_scope(message="The declared permission has an invalid data scope."):
    raise DataScopeDenied(message, error_code=ErrorCode.DATA_SCOPE_INVALID)


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_positive_int_values(values, message):
    if any(not _is_positive_int(value) for value in values):
        _invalid_scope(message)


def _validate_non_empty_string_values(values, message):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        _invalid_scope(message)


INTEGRATION_SCOPE_KEYS = {
    "platforms",
    "environments",
    "regions",
    "integration_config_ids",
    "resource_types",
    "store_ids",
    "warehouse_ids",
}
MARKETPLACE_PLATFORMS = {"lazada", "shopee", "tiktok"}
WAREHOUSE_AUTHORIZATION_RESOURCE_TYPE = "inventory_snapshot"


def _normalized_regions(values):
    """Normalize JSON region values for scope comparisons.

    Integration configuration regions are stored as a JSON list.  Keeping the
    comparison in one place also makes the queryset fall-back below safe for
    database backends that return JSON values as a serialized string.
    """
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _regions_fit_scope(candidate_regions, allowed_regions):
    """Return whether a config is fully contained by a region scope.

    An empty config region list means the integration applies globally, which
    is the same convention used by the existing integration-config filter.
    A multi-region config is only visible when every region is authorized.
    """
    candidate = _normalized_regions(candidate_regions)
    allowed = _normalized_regions(allowed_regions)
    return not candidate or candidate.issubset(allowed)


def permission_scope_configs(user, permission_code, relevant_keys, *, allowed_keys=None, incompatible_keys=(), resource_code=None):
    scopes = get_permission_data_scopes(user, permission_code, resource_code=resource_code)
    if not scopes:
        raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None
    if any(scope["scope_type"] in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT} for scope in scopes):
        raise DataScopeDenied(
            "The declared permission uses an unsupported data scope type.",
            error_code=ErrorCode.DATA_SCOPE_UNSUPPORTED,
        )

    configs = []
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            raise DataScopeDenied("The declared permission has an invalid data scope.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        config = scope.get("config") or {}
        if not isinstance(config, dict):
            _invalid_scope()
        allowed_keys = set(allowed_keys or relevant_keys)
        unknown_keys = set(config) - allowed_keys
        if unknown_keys:
            _invalid_scope("The declared permission data scope contains unsupported keys.")
        # This role cannot grant the requested resource when one of its
        # restrictions has no safe relation to that resource.  Skip the whole
        # role, never keep its other dimensions and silently widen access.
        if set(config) & set(incompatible_keys):
            continue
        selected = {key: config[key] for key in relevant_keys if key in config}
        if not selected:
            continue
        if any(not isinstance(values, list) or not values for values in selected.values()):
            _invalid_scope()
        configs.append(selected)
    if not configs:
        raise DataScopeDenied("The declared permission has no applicable data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    return configs


def analytics_dimension_configs(user, permission_code, *, resource_code=None):
    keys = {"analytics_dimensions"} | ({"store_ids", "sku_ids", "spu_ids", "warehouse_ids"} if resource_code else set())
    configs = permission_scope_configs(user, permission_code, keys, resource_code=resource_code)
    if configs is None:
        return None
    result = []
    allowed_keys = {"platform", "store_id", "country", "product_id", "sku_id", "warehouse_id"}
    string_keys = {"platform", "store_id", "country"}
    integer_keys = {"product_id", "sku_id", "warehouse_id"}
    for config in configs:
        if "analytics_dimensions" not in config:
            names = {"store_ids": "store_id", "sku_ids": "sku_id", "spu_ids": "product_id", "warehouse_ids": "warehouse_id"}
            result.append({names[key]: values for key, values in config.items()})
            continue
        dimensions = config["analytics_dimensions"]
        if any(not isinstance(item, dict) or not item or set(item) - allowed_keys for item in dimensions):
            _invalid_scope("Analytics data scope is invalid.")
        for item in dimensions:
            if any(not isinstance(item[key], str) or not item[key].strip() for key in set(item) & string_keys):
                _invalid_scope("Analytics data scope contains an invalid string dimension.")
            if any(not _is_positive_int(item[key]) for key in set(item) & integer_keys):
                _invalid_scope("Analytics data scope contains an invalid identifier dimension.")
        result.extend(dimensions)
    return result


def filter_analytics_queryset(user, queryset, permission_code):
    configs = analytics_dimension_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for dimensions in configs:
        condition = Q()
        for key, value in dimensions.items():
            condition &= Q(**{f"dimensions__{key}": value})
        allowed |= condition
    return queryset.filter(allowed)


def analytics_dimensions_allowed(user, permission_code, dimensions):
    configs = analytics_dimension_configs(user, permission_code)
    if configs is None:
        return True
    return any(all(dimensions.get(key) == value for key, value in scope.items()) for scope in configs)


def filter_lifecycle_queryset(user, queryset, permission_code):
    configs = permission_scope_configs(user, permission_code, {"spu_ids", "sku_ids"})
    if configs is None:
        return queryset
    for config in configs:
        for key in {"spu_ids", "sku_ids"} & set(config):
            _validate_positive_int_values(config[key], "Lifecycle data scope contains an invalid identifier.")
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "spu_ids" in config:
            condition &= Q(spu_id__in=config["spu_ids"])
        if "sku_ids" in config:
            condition &= Q(sku_id__in=config["sku_ids"])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def lifecycle_target_allowed(user, permission_code, *, spu_id=None, sku_id=None):
    configs = permission_scope_configs(user, permission_code, {"spu_ids", "sku_ids"})
    if configs is None:
        return True
    for config in configs:
        for key in {"spu_ids", "sku_ids"} & set(config):
            _validate_positive_int_values(config[key], "Lifecycle data scope contains an invalid identifier.")
        if "spu_ids" in config and spu_id not in set(config["spu_ids"]):
            continue
        if "sku_ids" in config and sku_id not in set(config["sku_ids"]):
            continue
        return True
    return False


def filter_integration_configs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        {"platforms", "environments", "regions", "integration_config_ids"},
        allowed_keys=INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(platform__in=[str(value) for value in config["platforms"]])
        if "integration_config_ids" in config:
            condition &= Q(pk__in=config["integration_config_ids"])
        if "environments" in config:
            condition &= Q(environment__in=config["environments"])
        if "regions" in config:
            allowed_regions = set(config["regions"])
            scoped_ids = [
                pk
                for pk, regions in queryset.filter(condition).values_list("pk", "regions")
                if set(regions or []).issubset(allowed_regions)
            ]
            allowed |= Q(pk__in=scoped_ids)
        else:
            allowed |= condition
    return queryset.filter(allowed).distinct()


def filter_store_authorizations(user, queryset, permission_code):
    from apps.masterdata.models import PlatformMaster, StoreMaster

    queryset = queryset.filter(tenant=user.tenant)
    # Product mapping shares its action grant with warehouse SKU. Resolve its
    # platform scope independently so one role can keep a warehouse default.
    configs = permission_scope_configs(
        user,
        permission_code,
        {
            "platforms",
            "platform_ids",
            "environments",
            "regions",
            "integration_config_ids",
            "resource_types",
            "store_ids",
        },
        allowed_keys=INTEGRATION_SCOPE_KEYS | {"platform_ids", "site_ids", "supplier_ids"},
        incompatible_keys={"warehouse_ids", "site_ids", "supplier_ids"},
        resource_code=(
            "integrations.product_mapping"
            if str(permission_code).startswith("integrations.product_mapping.") else None
        ),
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    for config in configs:
        if "platform_ids" in config:
            platform_ids = set(config["platform_ids"])
            if PlatformMaster.objects.filter(tenant=user.tenant, id__in=platform_ids).count() != len(platform_ids):
                raise DataScopeDenied(
                    "店铺授权的平台范围包含当前租户之外的对象。",
                    error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
                )
        if "platforms" in config:
            _validate_non_empty_string_values(config["platforms"], "Store authorization scope has an invalid platform.")
            if not set(config["platforms"]) <= MARKETPLACE_PLATFORMS:
                _invalid_scope("Store authorization scope contains an unsupported platform.")
        if "store_ids" in config:
            _validate_positive_int_values(config["store_ids"], "Store authorization scope has an invalid store identifier.")
            authorized_store_count = StoreMaster.objects.filter(
                tenant=user.tenant,
                id__in=set(config["store_ids"]),
            ).count()
            if authorized_store_count != len(set(config["store_ids"])):
                raise DataScopeDenied(
                    "Store authorization scope exceeds the current tenant.",
                    error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
                )
    allowed = Q(pk__in=[])
    region_ids = set()
    for config in configs:
        # Store authorization is a credential/binding resource rather than a
        # resource-specific sync record.  A resource_types restriction cannot
        # be mapped to this object without guessing which downstream job the
        # caller intends to inspect, so fail closed instead of broadening the
        # result set by ignoring that dimension.
        if "resource_types" in config:
            continue
        condition = Q()
        if "platform_ids" in config:
            condition &= Q(store__tenant=user.tenant, store__platform_id__in=config["platform_ids"])
            condition &= (
                Q(platform=F("store__platform__platform_type"))
                | Q(platform=F("store__platform__code"))
            )
        if "platforms" in config:
            condition &= Q(platform__in=config["platforms"])
        if "environments" in config:
            condition &= Q(integration_config__environment__in=config["environments"])
        if "integration_config_ids" in config:
            condition &= Q(integration_config_id__in=config["integration_config_ids"])
        if "store_ids" in config:
            condition &= Q(store_id__in=config["store_ids"])
        if "regions" in config:
            # Both the authorization's concrete region and its config's
            # region allowlist are part of the candidate.  A multi-region
            # config is only visible when it is entirely contained in the
            # role's region scope, matching filter_integration_configs.
            for authorization_id, authorization_region, config_regions in queryset.filter(condition).values_list(
                "pk",
                "region",
                "integration_config__regions",
            ):
                effective_regions = _normalized_regions(authorization_region)
                effective_regions |= _normalized_regions(config_regions)
                if _regions_fit_scope(effective_regions, config["regions"]):
                    region_ids.add(authorization_id)
        else:
            allowed |= condition
    return queryset.filter(allowed | Q(pk__in=region_ids)).distinct()


def filter_warehouse_authorizations(user, queryset, permission_code):
    """Apply the warehouse authorization data scope without leaking tenants."""
    from apps.masterdata.models import WarehouseMaster

    configs = permission_scope_configs(
        user,
        permission_code,
        {
            "platforms",
            "environments",
            "regions",
            "integration_config_ids",
            "resource_types",
            "warehouse_ids",
        },
        allowed_keys=INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    for config in configs:
        if "warehouse_ids" in config:
            _validate_positive_int_values(
                config["warehouse_ids"],
                "Warehouse authorization scope has an invalid warehouse identifier.",
            )
            warehouse_count = WarehouseMaster.objects.filter(
                tenant=user.tenant,
                id__in=set(config["warehouse_ids"]),
            ).count()
            if warehouse_count != len(set(config["warehouse_ids"])):
                raise DataScopeDenied(
                    "Warehouse authorization scope exceeds the current tenant.",
                    error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
                )
    allowed = Q(pk__in=[])
    region_ids = set()
    for config in configs:
        # A warehouse authorization is exclusively an inventory snapshot
        # resource.  A scope for another integration resource must not turn
        # into an unconstrained authorization query.
        if (
            "resource_types" in config
            and WAREHOUSE_AUTHORIZATION_RESOURCE_TYPE not in set(config["resource_types"])
        ):
            continue
        condition = Q()
        if "platforms" in config:
            condition &= Q(integration_config__platform__in=config["platforms"])
        if "environments" in config:
            condition &= Q(integration_config__environment__in=config["environments"])
        if "integration_config_ids" in config:
            condition &= Q(integration_config_id__in=config["integration_config_ids"])
        if "warehouse_ids" in config:
            condition &= Q(warehouse_id__in=config["warehouse_ids"])
        if "regions" in config:
            for authorization_id, candidate_regions, warehouse_country in queryset.filter(condition).values_list(
                "pk", "integration_config__regions", "warehouse__country_code"
            ):
                effective_regions = _normalized_regions(candidate_regions) | _normalized_regions(warehouse_country)
                if _regions_fit_scope(effective_regions, config["regions"]):
                    region_ids.add(authorization_id)
        else:
            allowed |= condition
    return queryset.filter(allowed | Q(pk__in=region_ids)).distinct()


def filter_store_mappings(user, queryset, permission_code):
    """Filter store mappings through their authorization scope.

    A store mapping is a downstream binding of a marketplace authorization;
    its visibility must therefore inherit the authorization's complete
    integration scope (platform, environment, region, config and store).
    Reusing the authorization helper preserves its fail-closed handling for
    unsupported ``resource_types`` and its AND-within/OR-across semantics.
    """
    from apps.integrations.models import MarketplaceStoreAuthorization

    queryset = queryset.filter(tenant=user.tenant)
    authorizations = filter_store_authorizations(
        user,
        MarketplaceStoreAuthorization.objects.all(),
        permission_code,
    ).filter(
        # Historical rows must not gain visibility merely because their
        # authorization FK is in scope while the denormalized identity points
        # at another tenant/store/platform.
        tenant=user.tenant,
    )
    return queryset.filter(
        authorization_id__in=Subquery(authorizations.values("pk")),
        platform=F("authorization__platform"),
        store_id=F("authorization__store_id"),
    ).distinct()


def integration_values_allowed(
    user,
    permission_code,
    *,
    platform=None,
    environment=None,
    regions=None,
    config_id=None,
    resource_type=None,
    store_id=None,
    warehouse_id=None,
):
    configs = permission_scope_configs(
        user,
        permission_code,
        INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return True
    _validate_integration_configs(configs)
    for config in configs:
        if "platforms" in config and platform not in set(config["platforms"]):
            continue
        if "environments" in config and environment not in set(config["environments"]):
            continue
        if "regions" in config and not _regions_fit_scope(regions, config["regions"]):
            continue
        if "integration_config_ids" in config and config_id not in set(config["integration_config_ids"]):
            continue
        if "resource_types" in config and resource_type not in set(config["resource_types"]):
            continue
        if "store_ids" in config and store_id not in set(config["store_ids"]):
            continue
        if "warehouse_ids" in config and warehouse_id not in set(config["warehouse_ids"]):
            continue
        return True
    return False


def filter_product_mappings(user, queryset, permission_code):
    """Filter product mappings through the scoped store-mapping chain."""
    from apps.integrations.models import MarketplaceStoreMapping

    queryset = queryset.filter(tenant=user.tenant)
    store_mappings = filter_store_mappings(
        user,
        MarketplaceStoreMapping.objects.all(),
        permission_code,
    )
    return queryset.filter(
        store_mapping_id__in=Subquery(store_mappings.values("pk")),
        platform=F("store_mapping__platform"),
    ).distinct()


PLATFORM_DETAIL_INCOMPATIBLE_SCOPE_MESSAGE = (
    "平台商品明细无法按仓库或供应商限定数据。请管理员从原仓库/供应商角色移除"
    "该页面权限，另建按平台、国家/站点或店铺限定的角色并授权；原角色的仓库/供应商范围请保留。"
)


def _platform_product_detail_scope_configs(user, permission_code):
    """Return validated scopes for the dimensions carried by product details.

    Platform product detail rows carry both a platform FK and a store FK.  A
    custom scope containing both dimensions therefore means the same row must
    match both values; it must not become a broad platform OR store filter.
    Empty custom scope objects and empty dimension lists deliberately produce
    no usable config so callers fail closed with ``queryset.none()``.
    """

    scopes = get_permission_data_scopes(user, permission_code)
    if not scopes:
        raise DataScopeDenied("平台商品明细权限缺少数据范围，请管理员重新配置角色。", error_code=ErrorCode.DATA_SCOPE_MISSING)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None

    configs = []
    allowed_keys = {"platforms", "platform_ids", "site_ids", "store_ids", "warehouse_ids", "supplier_ids"}
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            raise DataScopeDenied(
                "平台商品明细不支持此数据范围类型，请管理员重新配置角色。",
                error_code=ErrorCode.DATA_SCOPE_UNSUPPORTED,
            )
        raw_config = scope.get("config")
        if raw_config is None:
            raw_config = {}
        if not isinstance(raw_config, dict):
            _invalid_scope("平台商品明细的数据范围配置必须是对象。")
        unknown_keys = set(raw_config) - allowed_keys
        if unknown_keys:
            _invalid_scope("平台商品明细的数据范围包含不支持的字段：" + "、".join(sorted(unknown_keys)))
        if {"warehouse_ids", "supplier_ids"} & set(raw_config):
            _invalid_scope(PLATFORM_DETAIL_INCOMPATIBLE_SCOPE_MESSAGE)
        if not raw_config:
            continue

        normalized = {}
        empty_dimension = False
        if "platforms" in raw_config:
            values = raw_config["platforms"]
            if not isinstance(values, list):
                _invalid_scope("平台商品明细的历史平台范围必须是数组。")
            if not values:
                empty_dimension = True
            else:
                _validate_non_empty_string_values(
                    values,
                    "平台商品明细的历史平台范围包含无效标识。",
                )
                normalized["platforms"] = [str(value).strip().lower() for value in values]
        for key, label in (("platform_ids", "平台"), ("site_ids", "国家/站点"), ("store_ids", "店铺")):
            if key not in raw_config:
                continue
            values = raw_config[key]
            if not isinstance(values, list):
                _invalid_scope(f"平台商品明细的{label}范围必须是 ID 数组。")
            if not values:
                empty_dimension = True
            else:
                _validate_positive_int_values(values, f"平台商品明细的{label}范围包含无效 ID。")
                normalized[key] = values
        if not normalized or empty_dimension:
            continue
        configs.append(normalized)
    return configs


def filter_platform_product_details(user, queryset, permission_code):
    """Filter platform product details by tenant and aligned platform/store scope.

    ``ALL`` is tenant-wide. ``CUSTOM`` scopes are ORed across role scopes and
    ANDed within one scope. A missing or empty applicable custom scope returns
    an empty queryset, keeping the page and detail APIs fail closed.
    """

    queryset = queryset.filter(tenant=user.tenant)
    configs = _platform_product_detail_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    if not configs:
        return queryset.none()

    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            platforms = config["platforms"]
            condition &= (
                Q(platform__platform_type__in=platforms)
                | Q(platform__code__in=platforms)
            )
        if "platform_ids" in config:
            condition &= Q(platform_id__in=config["platform_ids"])
        if "site_ids" in config:
            condition &= Q(site_id__in=config["site_ids"])
        if "store_ids" in config:
            condition &= Q(store_id__in=config["store_ids"])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def platform_product_detail_target_allowed(user, permission_code, *, platform, store, site=None):
    """Apply the same manage scope to a new row before it is persisted."""

    configs = _platform_product_detail_scope_configs(user, permission_code)
    if configs is None:
        return True
    platform_values = {
        str(getattr(platform, "platform_type", "") or "").strip().lower(),
        str(getattr(platform, "code", "") or "").strip().lower(),
    }
    for config in configs:
        if "platforms" in config and not platform_values.intersection(config["platforms"]):
            continue
        if "platform_ids" in config and platform.pk not in config["platform_ids"]:
            continue
        if "site_ids" in config and (site is None or site.pk not in config["site_ids"]):
            continue
        if "store_ids" in config and store.pk not in config["store_ids"]:
            continue
        return True
    return False


# Keep the longer queryset-oriented alias available to API modules that use
# the naming convention of the other scope helpers.
filter_platform_product_detail_queryset = filter_platform_product_details


def filter_sync_jobs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        {
            "platforms",
            "environments",
            "regions",
            "integration_config_ids",
            "resource_types",
            "store_ids",
            "warehouse_ids",
        },
        allowed_keys=INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    region_ids = set()
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(integration_config__platform__in=[str(value) for value in config["platforms"]])
        if "environments" in config:
            condition &= Q(integration_config__environment__in=config["environments"])
        if "store_ids" in config:
            condition &= Q(store_authorization__store_id__in=config["store_ids"])
        if "warehouse_ids" in config:
            condition &= Q(warehouse_authorization__warehouse_id__in=config["warehouse_ids"])
        if "integration_config_ids" in config:
            condition &= Q(integration_config_id__in=config["integration_config_ids"])
        if "resource_types" in config:
            condition &= Q(resource_type__in=[str(value) for value in config["resource_types"]])
        if "regions" in config:
            for job_id, candidate_regions, store_region, warehouse_country in queryset.filter(condition).values_list(
                "pk",
                "integration_config__regions",
                "store_authorization__region",
                "warehouse_authorization__warehouse__country_code",
            ):
                effective_regions = _normalized_regions(candidate_regions)
                effective_regions |= _normalized_regions(store_region)
                effective_regions |= _normalized_regions(warehouse_country)
                if _regions_fit_scope(effective_regions, config["regions"]):
                    region_ids.add(job_id)
        else:
            allowed |= condition
    return queryset.filter(allowed | Q(pk__in=region_ids)).distinct()


def filter_sync_runs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        {
            "platforms",
            "environments",
            "regions",
            "integration_config_ids",
            "resource_types",
            "store_ids",
            "warehouse_ids",
        },
        allowed_keys=INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    region_ids = set()
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(sync_job__integration_config__platform__in=[str(value) for value in config["platforms"]])
        if "environments" in config:
            condition &= Q(sync_job__integration_config__environment__in=config["environments"])
        if "store_ids" in config:
            condition &= Q(sync_job__store_authorization__store_id__in=config["store_ids"])
        if "warehouse_ids" in config:
            condition &= Q(sync_job__warehouse_authorization__warehouse_id__in=config["warehouse_ids"])
        if "integration_config_ids" in config:
            condition &= Q(sync_job__integration_config_id__in=config["integration_config_ids"])
        if "resource_types" in config:
            condition &= Q(sync_job__resource_type__in=[str(value) for value in config["resource_types"]])
        if "regions" in config:
            for run_id, candidate_regions, store_region, warehouse_country in queryset.filter(condition).values_list(
                "pk",
                "sync_job__integration_config__regions",
                "sync_job__store_authorization__region",
                "sync_job__warehouse_authorization__warehouse__country_code",
            ):
                effective_regions = _normalized_regions(candidate_regions)
                effective_regions |= _normalized_regions(store_region)
                effective_regions |= _normalized_regions(warehouse_country)
                if _regions_fit_scope(effective_regions, config["regions"]):
                    region_ids.add(run_id)
        else:
            allowed |= condition
    return queryset.filter(allowed | Q(pk__in=region_ids)).distinct()


def _finance_scope_configs(user, permission_code):
    configs = permission_scope_configs(user, permission_code, {"platforms", "currencies"})
    if configs is None:
        return None
    for config in configs:
        if "platforms" in config:
            _validate_non_empty_string_values(config["platforms"], "Finance data scope contains an invalid platform.")
        if "currencies" in config:
            _validate_non_empty_string_values(config["currencies"], "Finance data scope contains an invalid currency.")
            if any(not re.fullmatch(r"[A-Z]{3}", value) for value in config["currencies"]):
                _invalid_scope("Finance data scope currencies must use uppercase ISO 4217 codes.")
    return configs


def finance_values_allowed(user, permission_code, *, platform, currency):
    configs = _finance_scope_configs(user, permission_code)
    if configs is None:
        return True
    return any(
        ("platforms" not in config or platform in set(config["platforms"]))
        and ("currencies" not in config or currency in set(config["currencies"]))
        for config in configs
    )


def filter_finance_queryset(user, queryset, permission_code, *, platform_field="platform", currency_field="currency"):
    configs = _finance_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(**{f"{platform_field}__in": [str(value) for value in config["platforms"]]})
        if "currencies" in config:
            condition &= Q(**{f"{currency_field}__in": [str(value).upper() for value in config["currencies"]]})
        allowed |= condition
    return queryset.filter(allowed).distinct()


REPORT_TYPES = {
    "analytics_summary",
    "inventory_alerts",
    "replenishment",
    "lifecycle",
    "business_alerts",
    "finance_summary",
    "sales_details",
    "self_service",
}


def _validate_integration_configs(configs):
    for config in configs:
        if "platform_ids" in config:
            _validate_positive_int_values(
                config["platform_ids"],
                "店铺授权的平台范围包含无效 ID。",
            )
        if "platforms" in config:
            _validate_non_empty_string_values(config["platforms"], "Integration data scope contains an invalid platform.")
        if "environments" in config:
            _validate_non_empty_string_values(
                config["environments"],
                "Integration data scope contains an invalid environment.",
            )
            if not set(config["environments"]) <= {"mock", "sandbox", "pilot", "production"}:
                _invalid_scope("Integration data scope contains an unsupported environment.")
        if "regions" in config:
            _validate_non_empty_string_values(config["regions"], "Integration data scope contains an invalid region.")
            if any(not re.fullmatch(r"[A-Z]{2,8}", region) for region in config["regions"]):
                _invalid_scope("Integration data scope regions must be uppercase platform codes.")
        if "integration_config_ids" in config:
            _validate_positive_int_values(
                config["integration_config_ids"],
                "Integration data scope contains an invalid configuration identifier.",
            )
        if "resource_types" in config:
            _validate_non_empty_string_values(
                config["resource_types"],
                "Integration data scope contains an invalid resource type.",
            )
        if "store_ids" in config:
            _validate_positive_int_values(
                config["store_ids"],
                "Integration data scope contains an invalid store identifier.",
            )
        if "warehouse_ids" in config:
            _validate_positive_int_values(
                config["warehouse_ids"],
                "Integration data scope contains an invalid warehouse identifier.",
            )


def report_types_for_permission(user, permission_code):
    configs = permission_scope_configs(user, permission_code, {"report_types"})
    if configs is None:
        return None
    report_types = set()
    for config in configs:
        _validate_non_empty_string_values(config["report_types"], "Report data scope contains an invalid report type.")
        values = set(config["report_types"])
        if not values <= REPORT_TYPES:
            raise DataScopeDenied("Report data scope is invalid.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        report_types.update(values)
    return report_types


def report_type_allowed(user, permission_code, report_type):
    report_types = report_types_for_permission(user, permission_code)
    return report_types is None or report_type in report_types


def filter_report_exports(user, queryset, permission_code):
    report_types = report_types_for_permission(user, permission_code)
    if report_types is None:
        return queryset
    return queryset.filter(report_type__in=report_types)
