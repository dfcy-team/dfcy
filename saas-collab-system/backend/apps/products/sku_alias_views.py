from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.common.responses import success_response
from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.permissions.ui_p5_scopes import filter_product_skus
from apps.tenants.models import Tenant
from .models import ProductSKU, ProductSKUAlias
from .permissions import IsProductMasterReadOrManage
from .sku_aliases import code_key


class AliasInput(serializers.Serializer):
    alias_code = serializers.CharField(max_length=160, trim_whitespace=False)
    effective_from = serializers.DateTimeField()
    effective_to = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=400)
    scope_type = serializers.ChoiceField(choices=["tenant", "store", "warehouse"], default="tenant")
    store_id = serializers.IntegerField(required=False, min_value=1)
    warehouse_id = serializers.IntegerField(required=False, min_value=1)


def alias_data(alias):
    fields = ("id", "alias_code", "scope_type", "store_id", "warehouse_id", "source", "reason", "version_no")
    return {**{key: getattr(alias, key) for key in fields}, **{key: getattr(alias, key).isoformat() if getattr(alias, key) else None for key in ("effective_from", "effective_to", "created_at", "updated_at")}}


def scoped_sku(request, pk):
    code = "products.master.view" if request.method == "GET" else "products.master.manage"
    return get_object_or_404(filter_product_skus(request.user, ProductSKU.objects.filter(tenant=request.user.tenant), code), pk=pk)


def create_alias(*, sku, actor, values, source="manual"):
    """Caller locks the tenant row to serialize interval checks across SKUs."""
    alias = values["alias_code"]
    start, end = values["effective_from"], values.get("effective_to")
    if not alias.strip() or "\x00" in alias or alias == sku.sku_code:
        raise ValidationError({"alias_code": "请填写不同于当前内部编码的有效历史编码。"})
    if end and end <= start:
        raise ValidationError({"effective_to": "结束时间必须晚于开始时间。"})
    scope = values.get("scope_type", "tenant")
    store_id, warehouse_id = values.get("store_id"), values.get("warehouse_id")
    if (scope == "tenant" and (store_id or warehouse_id)) or (scope == "store" and (not store_id or warehouse_id)) or (scope == "warehouse" and (not warehouse_id or store_id)):
        raise ValidationError({"scope_type": "来源范围与店铺/仓库不一致。"})
    for model, pk in ((StoreMaster, store_id), (WarehouseMaster, warehouse_id)):
        if pk and not model.objects.filter(tenant_id=sku.tenant_id, pk=pk).exists():
            raise ValidationError({"scope_type": "来源不在当前租户内。"})
    overlap = ProductSKUAlias.objects.filter(tenant_id=sku.tenant_id, code_key=code_key(alias)).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=start))
    if end:
        overlap = overlap.filter(effective_from__lt=end)
    if scope != "tenant":
        overlap = overlap.filter(Q(scope_type="tenant") | Q(scope_type=scope, store_id=store_id, warehouse_id=warehouse_id))
    if overlap.exists():
        raise ValidationError({"alias_code": "该编码在相同范围的生效期间已有映射，请先核对或结束原映射。"})
    # Current internal codes always identify their existing product.
    if ProductSKU.objects.filter(tenant_id=sku.tenant_id, sku_code=alias).exclude(pk=sku.pk).exists():
        raise ValidationError({"alias_code": "该编码已是另一个商品的当前内部编码。"})
    version = (ProductSKUAlias.objects.filter(sku=sku).aggregate(n=Max("version_no"))["n"] or 0) + 1
    item = ProductSKUAlias.objects.create(tenant_id=sku.tenant_id, sku=sku, code_key=code_key(alias), source=source, created_by=actor, version_no=version, **values)
    write_operation_log(tenant=sku.tenant, user=actor, module="products", action="product_sku.alias_create", object_type="ProductSKUAlias", object_id=item.pk, after_data=alias_data(item))
    return item


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def sku_alias_collection(request, pk):
    sku = scoped_sku(request, pk)
    if request.method == "GET":
        return success_response({"items": [alias_data(row) for row in ProductSKUAlias.objects.filter(tenant=request.user.tenant, sku=sku)[:200]]})
    data = AliasInput(data=request.data)
    data.is_valid(raise_exception=True)
    Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
    item = create_alias(sku=sku, actor=request.user, values=data.validated_data)
    return success_response(alias_data(item), status=201)


class AliasCloseInput(serializers.Serializer):
    effective_to = serializers.DateTimeField()
    reason = serializers.CharField(max_length=400)
    version_no = serializers.IntegerField(min_value=1)


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def sku_alias_close(request, pk, alias_id):
    sku = scoped_sku(request, pk)
    data = AliasCloseInput(data=request.data)
    data.is_valid(raise_exception=True)
    Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
    item = get_object_or_404(ProductSKUAlias.objects.select_for_update(), tenant=request.user.tenant, sku=sku, pk=alias_id)
    end = data.validated_data["effective_to"]
    if item.version_no != data.validated_data["version_no"]:
        raise ValidationError({"version_no": "记录已变更，请重新读取。"})
    if end <= item.effective_from or (item.effective_to and end >= item.effective_to):
        raise ValidationError({"effective_to": "只能缩短生效期间，结束时间必须晚于开始时间。"})
    before = alias_data(item)
    item.effective_to = end
    item.version_no = (ProductSKUAlias.objects.filter(sku=sku).aggregate(n=Max("version_no"))["n"] or 0) + 1
    item.save(update_fields=["effective_to", "version_no", "updated_at"])
    write_operation_log(tenant=request.user.tenant, user=request.user, module="products", action="product_sku.alias_close", object_type="ProductSKUAlias", object_id=item.pk, before_data=before, after_data={**alias_data(item), "close_reason": data.validated_data["reason"]})
    return success_response(alias_data(item))
