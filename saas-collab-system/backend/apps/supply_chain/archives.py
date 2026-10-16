from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .dates import business_date
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.masterdata.archive_code_rules import allocate_archive_code
from apps.masterdata.models import ArchiveCodeRule, SupplierMaster
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.products.models import ProductSKU
from apps.purchasing.supply_permissions import authorize_internal_supplier
from .models import FreightCompany, SupplierProductPrice, domain_write
from .permissions import MANAGE, VIEW, internal_orders
from .models import PurchaseOrder
from .services import _internal, _tenant_lock, _master, _version, _event, _prior_event, publish_price


def allowed_suppliers(actor, permission=VIEW):
    internal_orders(actor, PurchaseOrder.objects.all(), permission)
    query = SupplierMaster.objects.filter(tenant=actor.tenant)
    scopes = get_permission_data_scopes(actor, permission)
    if any(s["scope_type"] in {DataScope.ScopeType.ALL, DataScope.ScopeType.OWN} for s in scopes):
        return query
    ids = set()
    for scope in scopes:
        values = (scope.get("config") or {}).get("supplier_ids", [])
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM and isinstance(values, list):
            ids.update(int(x) for x in values if str(x).isdigit())
    return query.filter(pk__in=ids)


def authorize_archive_supplier(actor, supplier_id=None):
    """OWN authorizes own orders, not manual edits of shared supplier masters/prices.

    Automatic price observations remain derived from authorized saved orders and
    retain their source order/version. They are not a manual master-edit bypass.
    """
    scopes = get_permission_data_scopes(actor, MANAGE)
    if any(s["scope_type"] == DataScope.ScopeType.ALL for s in scopes):
        return
    for scope in scopes:
        values = (scope.get("config") or {}).get("supplier_ids", [])
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM and isinstance(values, list) and supplier_id in {int(x) for x in values if str(x).isdigit()}:
            return
    raise PermissionDenied("人工维护共享供应商档案或报价需要全部范围或指定供应商范围。")


def supplier_data(obj):
    return {"id": obj.pk, "version": obj.supply_version, **{name: getattr(obj, name) for name in (
        "code", "name", "contact_alias", "contact_phone", "contact_email", "province", "city",
        "factory_address", "loading_address", "tax_percent", "notes", "status", "payment_term_days", "payment_term_start")},
        "first_cooperation_date": obj.first_cooperation_date.isoformat() if obj.first_cooperation_date else None}


def freight_data(obj):
    return {"id": obj.pk, "version": obj.version, **{name: getattr(obj, name) for name in (
        "code", "name", "contact", "phone", "province", "city", "address", "shipping_marks",
        "fee_per_cbm", "tax_percent", "notes", "is_active")}}


def price_data(obj):
    return {"id": obj.pk, "version": obj.version, "supplier_id": obj.supplier_id,
            "supplier_name": obj.supplier.name, "sku_id": obj.sku_id, "sku": obj.sku.sku_code,
            "name": obj.sku.product_name, "unit_price": str(obj.unit_price),
            "effective_date": obj.effective_date, "source_kind": obj.source_kind,
            "source_order_id": obj.source_order_id, "source_order_version": obj.source_order_version,
            "notes": obj.notes}


def freight_scope(actor, permission=VIEW):
    internal_orders(actor, PurchaseOrder.objects.all(), permission)
    query = FreightCompany.objects.filter(tenant=actor.tenant)
    # Master references can be selected across suppliers; writes honor OWN.
    if permission == MANAGE and not any(s["scope_type"] == DataScope.ScopeType.ALL for s in get_permission_data_scopes(actor, permission)):
        query = query.filter(created_by=actor)
    return query


@transaction.atomic
def save_supplier(actor, payload, *, pk=None, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    values = dict(payload)
    expected = values.pop("expected_version", None)
    if pk:
        supplier = allowed_suppliers(actor, MANAGE).select_for_update().filter(pk=pk).first()
        if supplier is None:
            raise NotFound("供应商不可访问。")
        authorize_archive_supplier(actor, pk)
    else:
        scopes = get_permission_data_scopes(actor, MANAGE)
        if not any(s["scope_type"] == DataScope.ScopeType.ALL for s in scopes):
            raise PermissionDenied("指定供应商范围账号不能新增供应商。")
        supplier = SupplierMaster(tenant=actor.tenant)
    # SupplierMaster is shared with masterdata; audit uses its real model name.
    from .models import BusinessEvent
    prior = BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type="suppliermaster", action="archive_saved", request_key=idempotency_key).first()
    from .services import request_hash, _key
    _key(idempotency_key)
    digest_payload = {"id": pk, "values": payload}
    if prior:
        if prior.request_hash != request_hash(digest_payload):
            raise ValidationError("此请求编号已用于不同内容。")
        obj = allowed_suppliers(actor, MANAGE).filter(pk=prior.aggregate_id).first()
        if not obj:
            raise NotFound("供应商不可访问。")
        return obj
    if pk and expected != supplier.supply_version:
        raise ValidationError("供应商资料已改变，请刷新后再编辑。")
    if not pk and not values.get("code"):
        values["code"] = allocate_archive_code(actor.tenant, ArchiveCodeRule.Kind.SUPPLIER)
    if pk and "code" in values and not values["code"]:
        raise ValidationError({"code": "已有供应商的编码不能为空。"})
    for name, value in values.items():
        setattr(supplier, name, value)
    supplier.full_clean()
    supplier.save()
    with domain_write():
        BusinessEvent.objects.create(tenant=actor.tenant, created_by=actor, aggregate_type="suppliermaster",
            aggregate_id=supplier.pk, aggregate_version=supplier.supply_version,
            action="archive_saved", request_key=idempotency_key, request_hash=request_hash(digest_payload),
            payload={"after": {k: str(v) if k == "tax_percent" else v for k, v in supplier_data(supplier).items()}})
    return supplier


@transaction.atomic
def save_freight(actor, payload, *, pk=None, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    from .models import BusinessEvent
    from .services import _key, request_hash
    _key(idempotency_key)
    data = {"id": pk, "values": payload}
    prior = BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type="freightcompany", action="archive_saved", request_key=idempotency_key).first()
    if prior:
        if prior.request_hash != request_hash(data):
            raise ValidationError("此请求编号已用于不同内容。")
        obj = freight_scope(actor, MANAGE).filter(pk=prior.aggregate_id).first()
        if not obj:
            raise NotFound("货运公司不可访问。")
        return obj
    values = dict(payload)
    expected = values.pop("expected_version", None)
    obj = freight_scope(actor, MANAGE).filter(pk=pk).first() if pk else FreightCompany(tenant=actor.tenant, created_by=actor)
    if obj is None:
        raise NotFound("货运公司不可访问。")
    if pk:
        _version(obj, expected)
    elif not values.get("code"):
        values["code"] = allocate_archive_code(actor.tenant, ArchiveCodeRule.Kind.FREIGHT)
    if pk and "code" in values and not values["code"]:
        raise ValidationError({"code": "已有货运公司的编码不能为空。"})
    with domain_write():
        for name, value in values.items():
            setattr(obj, name, value)
        obj.version += 1 if pk else 0
        obj.save()
        _event(actor, obj, "archive_saved", idempotency_key, data)
    return obj


@transaction.atomic
def save_price(actor, payload, *, idempotency_key):
    _internal(actor)
    _tenant_lock(actor)
    supplier = _master(SupplierMaster, actor, payload["supplier_id"], status="active")
    authorize_archive_supplier(actor, supplier.pk)
    sku = _master(ProductSKU, actor, payload["sku_id"], is_active=True)
    obj = SupplierProductPrice.objects.filter(tenant=actor.tenant, supplier=supplier, sku=sku).first()
    if obj and _prior_event(actor, obj, "price_maintained", idempotency_key, payload):
        return obj
    if payload["expected_version"] != (obj.version if obj else 0):
        raise ValidationError("供应商价格已改变，请刷新后再编辑。")
    if payload["effective_date"] > business_date():
        raise ValidationError("不支持预约生效价格。")
    with domain_write():
        obj = publish_price(actor, supplier, sku, payload["unit_price"], payload["effective_date"], notes=payload.get("notes", ""))
        _event(actor, obj, "price_maintained", idempotency_key, payload)
    return obj
