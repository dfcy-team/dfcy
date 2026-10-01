"""Resource scope schemas. An override never grants an operation by itself."""
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import UserRole

RESOURCE_DEFINITIONS = {
    "platform_product_details": {"name": "平台商品明细", "dimensions": ["platform_ids", "site_ids", "store_ids"], "prefixes": ["listings.product_detail."]},
    "warehouse_authorizations": {"name": "仓库连接与库存数据", "dimensions": ["warehouse_ids"], "prefixes": ["integrations.warehouse."]},
    "products.master": {"name": "商品主数据", "dimensions": ["sku_ids", "spu_ids"], "prefixes": ["products.master."]},
    "products.cost": {"name": "商品成本", "dimensions": ["sku_ids", "spu_ids", "warehouse_ids"], "prefixes": ["products.cost."]},
    "sales_management.sales": {"name": "销售商品数据", "dimensions": ["store_ids"], "prefixes": ["sales_management."]},
    "commerce.inventory": {"name": "库存商品数据", "dimensions": ["warehouse_ids", "sku_ids", "spu_ids"], "prefixes": []},
    **{f"masterdata.{resource}": {"name": name, "dimensions": [dimension], "prefixes": []}
       for resource, name, dimension in (
           ("platforms", "平台资料", "platform_ids"), ("sites", "国家与站点", "site_ids"),
           ("stores", "店铺资料", "store_ids"), ("warehouses", "仓库资料", "warehouse_ids"),
           ("suppliers", "供应商资料", "supplier_ids"))},
}


def permission_resource(permission_code):
    for resource, definition in RESOURCE_DEFINITIONS.items():
        if any(str(permission_code).startswith(prefix) for prefix in definition["prefixes"]):
            return resource
    return None


def active_bindings(user):
    now = timezone.now()
    queryset = UserRole.objects.filter(
        tenant_id=user.tenant_id, user=user, role__tenant_id=user.tenant_id,
        role__status="active", status="active",
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=now))
    membership_id = getattr(user, "_active_membership_id", None)
    context = Q(membership__isnull=True)
    if membership_id is not None:
        context |= Q(membership_id=membership_id, membership__user_id=user.pk, membership__tenant_id=user.tenant_id,
                     membership__status="active", membership__department__status="active") & (
            Q(membership__valid_until__isnull=True) | Q(membership__valid_until__gt=now)
        )
    return queryset.filter(context)


def validate_resource_policy(tenant_id, resource_code, scope_type, config):
    from apps.masterdata.models import PlatformMaster, CountrySiteMaster, StoreMaster, WarehouseMaster, SupplierMaster
    from apps.products.models import ProductSKU, ProductSPU
    definition = RESOURCE_DEFINITIONS.get(resource_code)
    if definition is None:
        raise ValidationError("资源未登记范围适配器。")
    if not isinstance(config, dict):
        raise ValidationError("资源范围配置必须是对象。")
    if scope_type == "all":
        if config not in ({}, {"all": True}):
            raise ValidationError("全部范围只能使用 all=true。")
        return {"all": True}
    if scope_type != "custom" or not config:
        raise ValidationError("资源自定义范围至少选择一个有效维度。")
    unknown = set(config) - set(definition["dimensions"])
    if unknown:
        raise ValidationError("此资源不支持范围字段：" + "、".join(sorted(unknown)))
    models = {"platform_ids": PlatformMaster, "site_ids": CountrySiteMaster, "store_ids": StoreMaster,
              "warehouse_ids": WarehouseMaster, "supplier_ids": SupplierMaster,
              "sku_ids": ProductSKU, "spu_ids": ProductSPU}
    normalized = {}
    for key, values in config.items():
        if not isinstance(values, list) or not values or any(type(value) is not int or value < 1 for value in values):
            raise ValidationError(f"{key} 必须为非空正整数 ID 数组。")
        ids = sorted(set(values))
        if set(models[key].objects.filter(tenant_id=tenant_id, pk__in=ids).values_list("pk", flat=True)) != set(ids):
            raise ValidationError(f"{key} 包含不存在或其他租户的对象。")
        normalized[key] = ids
    return normalized
