"""Procurement manages scoped supplier contacts, never staff/admin identities."""
from django.contrib.auth.password_validation import validate_password
from django.db import transaction, IntegrityError
from django.utils.crypto import salted_hmac
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from django.core.exceptions import ValidationError
from rest_framework.response import Response
from apps.accounts.models import CustomUser, ExternalUserProfile
from .api import key, validated
from .archives import allowed_suppliers, authorize_archive_supplier
from .models import BusinessEvent, SupplierContactAccount, domain_write
from .permissions import MANAGE, VIEW
from .services import _event, _internal, _matching_replay, _prior_event, _tenant_lock, _version, request_hash
from .views import InternalAPI, _page


class ContactInput(serializers.Serializer):
    username = serializers.RegexField(r"^[a-zA-Z0-9_.@+-]{3,100}$", required=False)
    full_name = serializers.CharField(max_length=100, allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, required=False, max_length=128, trim_whitespace=False)
    is_active = serializers.BooleanField(required=False)
    expected_version = serializers.IntegerField(min_value=1, required=False)


def account_data(obj):
    return {"id": obj.pk, "supplier_id": obj.supplier_id, "username": obj.user.username,
            "full_name": obj.user.full_name, "is_active": obj.user.is_active, "version": obj.version}


def supplier_for(actor, pk, permission):
    supplier = allowed_suppliers(actor, permission).filter(pk=pk, status="active").first()
    if not supplier:
        raise NotFound("供应商不可访问。")
    return supplier


@transaction.atomic
def save_contact(actor, supplier_id, payload, request_key, pk=None):
    _internal(actor)
    _tenant_lock(actor)
    supplier = supplier_for(actor, supplier_id, MANAGE)
    authorize_archive_supplier(actor, supplier.pk)
    safe = {name: value for name, value in payload.items() if name != "password"}
    # Only a server-keyed fingerprint is retained for credential retry detection.
    fingerprint = {**safe, "supplier_id": supplier_id,
        "credential_fingerprint": salted_hmac("sc2-contact", payload.get("password", ""), algorithm="sha256").hexdigest()}
    if pk:
        obj = SupplierContactAccount.objects.select_related("user").filter(tenant=actor.tenant, supplier=supplier, pk=pk).first()
        if not obj:
            raise NotFound("供应商账号不可访问。")
        if _prior_event(actor, obj, "account_updated", request_key, fingerprint):
            return obj
        _version(obj, payload.get("expected_version"))
        if payload.get("username", obj.user.username) != obj.user.username:
            raise ValidationError("账号名称创建后不能修改。")
        user = CustomUser.objects.select_for_update().get(pk=obj.user_id)
        if user.user_type != "external" or user.tenant_id != actor.tenant_id or user.is_staff or user.is_superuser:
            raise ValidationError("账号身份已变化，不能通过供应商联系人入口维护。")
        profile = ExternalUserProfile.objects.select_for_update().filter(user=user, tenant=actor.tenant, supplier_id=supplier.pk).first()
        if not profile:
            raise ValidationError("账号供应商绑定已变化，请先核查。")
    else:
        event = BusinessEvent.objects.filter(tenant=actor.tenant, aggregate_type="suppliercontactaccount", action="account_created", request_key=request_key).first()
        if event:
            _matching_replay(event, request_hash(fingerprint))
            return SupplierContactAccount.objects.select_related("user").get(pk=event.aggregate_id, supplier=supplier)
        if not payload.get("username") or not payload.get("password"):
            raise ValidationError("创建联系人须填写账号和初始密码。")
        if CustomUser.objects.filter(username=payload["username"]).exists():
            raise ValidationError("此账号名称不可用，请更换。")
        user = CustomUser(username=payload["username"], tenant=actor.tenant, user_type="external", is_staff=False, is_superuser=False)
        profile = None
    if payload.get("password"):
        validate_password(payload["password"], user=user)
        user.set_password(payload["password"])
    user.full_name = payload.get("full_name", user.full_name)
    user.is_active = payload.get("is_active", user.is_active)
    try:
        user.save()
    except IntegrityError:
        raise ValidationError("此账号名称不可用，请更换。")
    if not profile:
        ExternalUserProfile.objects.create(user=user, tenant=actor.tenant, supplier_id=supplier.pk,
            company_name=supplier.name[:100], contact_name=user.full_name[:100])
    else:
        profile.contact_name = user.full_name[:100]
        profile.save()
    with domain_write():
        if not pk:
            obj = SupplierContactAccount.objects.create(tenant=actor.tenant, created_by=actor, supplier=supplier, user=user)
        else:
            obj.version += 1
            obj.save()
        _event(actor, obj, "account_updated" if pk else "account_created", request_key, fingerprint,
            audit={"account_snapshot": account_data(obj), "password_changed": bool(payload.get("password"))})
    return obj


class SupplierContacts(InternalAPI):
    def get(self, request, supplier_id):
        supplier = supplier_for(request.user, supplier_id, VIEW)
        return _page(request, SupplierContactAccount.objects.filter(tenant=request.user.tenant, supplier=supplier).select_related("user"), account_data)

    def post(self, request, supplier_id):
        obj = save_contact(request.user, supplier_id, validated(ContactInput, request), key(request))
        return Response({"data": account_data(obj)}, status=201)


class SupplierContactDetail(InternalAPI):
    def patch(self, request, supplier_id, pk):
        obj = save_contact(request.user, supplier_id, validated(ContactInput, request), key(request), pk=pk)
        return Response({"data": account_data(obj)})
