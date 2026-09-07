"""Explicit product actions that are intentionally separate from edit serializers.

SPU lifecycle/sales status fields are controlled fields on the normal
serializer.  These endpoints provide the deliberate, auditable action used by
the product master UI without reopening arbitrary serializer PATCH updates.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.common.responses import success_response
from apps.permissions.ui_p5_scopes import filter_product_skus, filter_product_spus

from .models import ProductSKU, ProductSPU
from .permissions import IsProductMasterReadOrManage
from .serializers import ProductSKUSerializer, ProductSPUSerializer


def _status_payload(request, allowed):
    payload = request.data
    if not hasattr(payload, "keys"):
        raise ValidationError("状态请求体必须是对象。")
    unknown = set(payload.keys()) - set(allowed)
    if unknown:
        raise ValidationError({field: "Unsupported status field." for field in sorted(unknown)})
    return payload


def _reason(payload):
    value = str(payload.get("reason") or "").strip()
    return value[:500]


@api_view(["POST", "PATCH"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_spu_status_action(request, pk):
    """Change an SPU lifecycle/sales status through an explicit action."""

    queryset = filter_product_spus(
        request.user,
        ProductSPU.objects.filter(tenant=request.user.tenant),
        "products.master.manage",
    ).select_for_update()
    item = get_object_or_404(queryset, pk=pk)
    payload = _status_payload(request, {"lifecycle_status", "sales_status", "reason"})
    fields = {field for field in ("lifecycle_status", "sales_status") if field in payload}
    if not fields:
        raise ValidationError("至少提供 lifecycle_status 或 sales_status。")

    updates = {}
    if "lifecycle_status" in payload:
        value = str(payload.get("lifecycle_status") or "").strip()
        if value not in ProductSPU.LifecycleStatus.values:
            raise ValidationError({"lifecycle_status": "Unsupported lifecycle status."})
        updates["lifecycle_status"] = value
    if "sales_status" in payload:
        value = str(payload.get("sales_status") or "").strip()
        if value not in ProductSPU.SalesStatus.values:
            raise ValidationError({"sales_status": "Unsupported sales status."})
        updates["sales_status"] = value

    before = {
        "lifecycle_status": item.lifecycle_status,
        "sales_status": item.sales_status,
    }
    changed = [field for field, value in updates.items() if getattr(item, field) != value]
    if changed:
        for field in changed:
            setattr(item, field, updates[field])
        item.save(update_fields=[*changed, "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="products",
            action="product_spu.status",
            object_type="ProductSPU",
            object_id=item.id,
            before_data=before,
            after_data={**before, **updates, "reason": _reason(payload)},
        )
    return success_response(ProductSPUSerializer(item).data)


def _parse_active(payload):
    supplied = []
    if "is_active" in payload:
        value = payload.get("is_active")
        if isinstance(value, bool):
            supplied.append(value)
        elif isinstance(value, (int, float)) and value in (0, 1):
            supplied.append(bool(value))
        elif isinstance(value, str) and value.strip().casefold() in {"true", "1", "active", "on_sale", "在售", "启用"}:
            supplied.append(True)
        elif isinstance(value, str) and value.strip().casefold() in {"false", "0", "inactive", "off_sale", "下架", "停用"}:
            supplied.append(False)
        else:
            raise ValidationError({"is_active": "商品状态必须是布尔值。"})
    if "status" in payload:
        value = str(payload.get("status") or "").strip().casefold()
        if value in {"active", "on_sale", "on sale", "在售", "启用", "true", "1"}:
            supplied.append(True)
        elif value in {"inactive", "off_sale", "off sale", "下架", "停用", "false", "0"}:
            supplied.append(False)
        else:
            raise ValidationError({"status": "商品状态只能是 active 或 inactive。"})
    if not supplied:
        raise ValidationError("请提供 is_active 或 status。")
    if len(set(supplied)) != 1:
        raise ValidationError("is_active 和 status 的状态值不一致。")
    return supplied[0]


@api_view(["POST", "PATCH"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_sku_status_action(request, pk):
    """Change a SKU's sale availability without triggering platform writes."""

    # ``filter_product_skus`` adds ``distinct()`` for its SPU-or-SKU scope
    # predicate.  PostgreSQL rejects ``FOR UPDATE`` on a DISTINCT query, so
    # first resolve visibility without a lock and then lock the base SKU row
    # through a plain primary-key subquery.
    visible_ids = filter_product_skus(
        request.user,
        ProductSKU.objects.filter(tenant=request.user.tenant),
        "products.master.manage",
    ).filter(pk=pk).values("pk")
    queryset = ProductSKU.objects.filter(
        tenant=request.user.tenant,
        pk__in=visible_ids,
    ).select_for_update(of=("self",))
    item = get_object_or_404(queryset, pk=pk)
    payload = _status_payload(request, {"is_active", "status", "reason"})
    value = _parse_active(payload)
    before = {"is_active": item.is_active}
    if item.is_active != value:
        item.is_active = value
        item.save(update_fields=["is_active", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="products",
            action="product_sku.status",
            object_type="ProductSKU",
            object_id=item.id,
            before_data=before,
            after_data={"is_active": value, "reason": _reason(payload)},
        )
    return success_response(ProductSKUSerializer(item).data)
