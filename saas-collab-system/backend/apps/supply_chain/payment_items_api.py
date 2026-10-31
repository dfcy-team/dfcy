from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.purchasing.supply_permissions import require_internal_supply_permission
from apps.tenants.models import Tenant
from .models import BusinessEvent, PaymentItem, domain_write
from .permissions import MANAGE, VIEW
from .views import InternalAPI

FIELDS = ("name", "party_type", "default_nature", "default_tax_rate", "counts_as_cost", "default_allocation", "is_active", "sort_order")
DEFAULTS = [("报关费", "carrier", "corporate"), ("拖车费", "carrier", "corporate"), ("国际海运费", "carrier", "corporate"), ("港杂费", "carrier", "corporate"), ("海外清关费", "carrier", "personal")]

class ItemInput(serializers.Serializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    party_type = serializers.ChoiceField(choices=["supplier", "carrier", "both"])
    default_nature = serializers.ChoiceField(choices=["corporate", "personal"])
    default_tax_rate = serializers.DecimalField(max_digits=6, decimal_places=3, min_value=0, max_value=100, required=False, allow_null=True)
    counts_as_cost = serializers.BooleanField()
    default_allocation = serializers.ChoiceField(choices=["volume", "weight", "mixed"])
    is_active = serializers.BooleanField()
    sort_order = serializers.IntegerField(min_value=0)
    expected_version = serializers.IntegerField(min_value=0, required=False)
    reason = serializers.CharField(max_length=300, trim_whitespace=True, required=False, allow_blank=True)

def _can_manage(user):
    try:
        require_internal_supply_permission(user, MANAGE)
        return any(s["scope_type"] == DataScope.ScopeType.ALL for s in get_permission_data_scopes(user, MANAGE))
    except PermissionDenied:
        return False

def _data(row):
    return {"id": row.pk, "version": row.version, **{field: getattr(row, field) for field in FIELDS}}

class PaymentItems(InternalAPI):
    def get(self, request):
        user = request.user
        require_internal_supply_permission(user, VIEW)
        return Response({"data": {"items": [_data(x) for x in PaymentItem.objects.filter(tenant_id=user.tenant_id)], "can_manage": _can_manage(user)}})

    @transaction.atomic
    def post(self, request):
        return self._save(request, None)

    def _save(self, request, item):
        user = request.user
        require_internal_supply_permission(user, MANAGE)
        if not _can_manage(user): raise PermissionDenied("维护付款项目需要全部数据范围。")
        data = ItemInput(data=request.data); data.is_valid(raise_exception=True); payload = data.validated_data
        key = request.headers.get("Idempotency-Key")
        if not key or len(key) > 128: raise ValidationError("需要有效的 Idempotency-Key。")
        from .services import _event, _matching_replay, request_hash
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        event_payload = {**payload, "_idempotency_action": "update" if item else "create", "_target_id": item or None}
        digest = request_hash(event_payload)
        prior = BusinessEvent.objects.filter(tenant_id=user.tenant_id, aggregate_type="paymentitem", action="payment_item_updated", request_key=key).first()
        if prior:
            _matching_replay(prior, digest)
            return Response({"data": _data(PaymentItem.objects.get(pk=prior.aggregate_id, tenant_id=user.tenant_id))})
        if item:
            from django.shortcuts import get_object_or_404
            item = get_object_or_404(PaymentItem.objects.select_for_update(), pk=item, tenant_id=user.tenant_id)
            if payload.get("expected_version") != item.version: raise ValidationError("付款项目已更新，请刷新后重试。")
        values = {k: payload[k] for k in FIELDS if k in payload}
        if PaymentItem.objects.filter(tenant_id=user.tenant_id, name=values["name"]).exclude(pk=getattr(item, "pk", None)).exists():
            raise ValidationError({"name": "此付款项目名称已存在。"})
        with domain_write():
            if item:
                for k,v in values.items(): setattr(item,k,v)
                item.version += 1; item.save()
            else: item = PaymentItem.objects.create(tenant=user.tenant, created_by=user, **values)
            _event(user, item, "payment_item_updated", key, event_payload, audit={"reason":payload.get("reason", "")})
        return Response({"data": _data(item)})

class PaymentItemDetail(PaymentItems):
    def get(self, request, pk): raise MethodNotAllowed("GET")
    def post(self, request, pk): raise MethodNotAllowed("POST")
    @transaction.atomic
    def patch(self, request, pk): return self._save(request, pk)

class InitializePaymentItems(PaymentItems):
    @transaction.atomic
    def post(self, request):
        user = request.user
        require_internal_supply_permission(user, MANAGE)
        if not _can_manage(user): raise PermissionDenied("初始化付款项目需要全部数据范围。")
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        if not PaymentItem.objects.filter(tenant_id=user.tenant_id).exists():
            with domain_write():
                for index, (name, party, nature) in enumerate(DEFAULTS):
                    PaymentItem.objects.create(tenant=user.tenant, created_by=user, name=name, party_type=party,
                        default_nature=nature, counts_as_cost=True, default_allocation="volume", sort_order=index)
        return Response({"data": {"items": [_data(x) for x in PaymentItem.objects.filter(tenant_id=user.tenant_id)], "can_manage": True}})
