import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.tenants.models import Tenant
from apps.permissions.api_permissions import (
    IsFeishuApprovalUser,
    IsFeishuConnectionUser,
    IsFeishuIdentityUser,
    IsFeishuNotificationUser,
    IsFeishuOperationsViewer,
    IsFeishuReportUser,
)

from .custody import CustodyError, get_custody_backend
from .models import FeishuConfigRule, FeishuConnection, FeishuIdentity, FeishuOperation
from .feishu_identity_service import FeishuIdentityService, masked_contacts


SECRET_INPUTS = {
    "app_secret": "app_secret_ref",
    "verification_token": "verification_token_ref",
    "encrypt_key": "encrypt_key_ref",
}


def _store_secret_reference(*, tenant_id, kind, value):
    try:
        result = get_custody_backend().store_secrets(
            credential_type=f"feishu_{kind}",
            reference_version=1,
            # Custody deliberately rejects metadata key names that look like
            # secret-bearing fields.  This value is only a non-sensitive role
            # label, so keep the key outside that deny-list contract.
            metadata={"tenant_id": tenant_id, "value_role": kind},
            operation_id=uuid.uuid4().hex,
            app_secret=str(value),
        )
    except CustodyError as exc:
        raise ValidationError({kind: str(exc)}) from exc
    return str(result["credential_id"])


def _connection_data(obj):
    return {
        "app_id": obj.app_id,
        "domain": obj.domain,
        "callback_url": obj.callback_url,
        "enabled": obj.enabled,
        "status": "configured" if obj.app_id and obj.app_secret_ref else "unconfigured",
        "credential_configured": bool(obj.app_secret_ref),
        "verification_token_configured": bool(obj.verification_token_ref),
        "encrypt_key_configured": bool(obj.encrypt_key_ref),
        "updated_at": obj.updated_at,
        "external_calls_enabled": False,
    }


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsFeishuConnectionUser])
def connection_detail(request):
    obj = FeishuConnection.objects.filter(tenant=request.user.tenant).first()
    if request.method == "GET":
        if obj is None:
            return success_response({
                "app_id": "", "domain": "feishu", "callback_url": "", "enabled": False,
                "status": "unconfigured", "credential_configured": False,
                "verification_token_configured": False, "encrypt_key_configured": False,
                "updated_at": None, "external_calls_enabled": False,
            })
        return success_response(_connection_data(obj))

    payload = request.data if isinstance(request.data, dict) else {}
    allowed = {"app_id", "domain", "callback_url", "enabled", *SECRET_INPUTS}
    unsupported = set(payload) - allowed
    if unsupported:
        raise ValidationError({"detail": f"Unsupported fields: {', '.join(sorted(unsupported))}"})
    if payload.get("domain", obj.domain if obj else "feishu") not in {"feishu", "lark"}:
        raise ValidationError({"domain": "Must be feishu or lark."})
    obj, _ = FeishuConnection.objects.get_or_create(
        tenant=request.user.tenant,
        defaults={"created_by": request.user, "updated_by": request.user},
    )
    for field in ("app_id", "domain", "callback_url", "enabled"):
        if field in payload:
            setattr(obj, field, payload[field])
    for input_name, storage_name in SECRET_INPUTS.items():
        if input_name in payload:
            value = payload[input_name]
            setattr(
                obj,
                storage_name,
                _store_secret_reference(tenant_id=request.user.tenant_id, kind=input_name, value=value) if value else "",
            )
    obj.updated_by = request.user
    obj.save()
    return success_response(_connection_data(obj))


def _identity_data(obj):
    return {
        "id": obj.id, "user_id": obj.feishu_user_id, "system_user_id": obj.user_id,
        "username": obj.user.username, "open_id": obj.open_id, "union_id": obj.union_id,
        "department_ids": obj.department_ids, "status": obj.status, "updated_at": obj.updated_at,
    }


@api_view(["GET"])
@permission_classes([IsFeishuIdentityUser])
def identity_collection(request):
    users = get_user_model().objects.filter(tenant=request.user.tenant).select_related(
        "internal_profile", "internal_profile__department"
    )
    mappings = {
        item.user_id: item for item in FeishuIdentity.objects.filter(tenant=request.user.tenant).select_related("user")
    }
    items = []
    for user in users.order_by("id"):
        mapping = mappings.get(user.id)
        profile = getattr(user, "internal_profile", None)
        items.append({
            "system_user_id": user.id, "username": user.username, "full_name": user.full_name,
            "employee_no": profile.employee_no if profile else "",
            "department": profile.department.name if profile and profile.department else "",
            "contacts": masked_contacts(user), "mapping": _identity_data(mapping) if mapping else None,
        })
    return success_response({"items": items})


@api_view(["POST"])
@permission_classes([IsFeishuIdentityUser])
def identity_candidates(request, system_user_id):
    user = get_object_or_404(get_user_model(), pk=system_user_id, tenant=request.user.tenant)
    connection = FeishuConnection.objects.filter(tenant=request.user.tenant).first()
    candidates = FeishuIdentityService().find_candidates(connection=connection, user=user)
    return success_response({"system_user_id": user.id, "candidates": candidates})


@api_view(["PUT"])
@permission_classes([IsFeishuIdentityUser])
def identity_bind(request, system_user_id):
    user = get_object_or_404(get_user_model(), pk=system_user_id, tenant=request.user.tenant)
    payload = request.data if isinstance(request.data, dict) else {}
    open_id = str(payload.get("open_id") or "").strip()
    if not open_id:
        raise ValidationError({"open_id": "open_id is required."})
    connection = FeishuConnection.objects.filter(tenant=request.user.tenant).first()
    verified = next(
        (
            candidate for candidate in FeishuIdentityService().find_candidates(connection=connection, user=user)
            if candidate["open_id"] == open_id
        ),
        None,
    )
    if verified is None:
        raise ValidationError({"open_id": "该飞书用户不在当前系统用户的查询候选中，请重新查询。"})
    with transaction.atomic():
        # Serialize identity binding within one tenant so the duplicate check
        # and update cannot race for two different system users.
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        if FeishuIdentity.objects.filter(
            tenant=request.user.tenant, open_id=open_id
        ).exclude(user=user).exists():
            raise ValidationError({"open_id": "该飞书用户已绑定其他系统用户。"})
        obj, _ = FeishuIdentity.objects.update_or_create(
            tenant=request.user.tenant, user=user,
            defaults={
                "open_id": open_id, "feishu_user_id": verified["user_id"],
                "union_id": verified["union_id"],
                "department_ids": verified["department_ids"], "status": "active",
            },
        )
    return success_response(_identity_data(obj))


@api_view(["GET", "DELETE"])
@permission_classes([IsFeishuIdentityUser])
def identity_detail(request, pk):
    obj = get_object_or_404(FeishuIdentity.objects.select_related("user"), pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(_identity_data(obj))
    if request.method == "DELETE":
        obj.delete()
        return success_response({"deleted": True})
    for field in ("open_id", "union_id", "department_ids", "status"):
        if field in request.data:
            setattr(obj, field, request.data[field])
    if "user_id" in request.data:
        obj.feishu_user_id = request.data["user_id"]
    obj.save()
    return success_response(_identity_data(obj))


def _rule_data(obj):
    return {"id": obj.id, "name": obj.name, "code": obj.code, "enabled": obj.enabled,
            "config": obj.config, "created_at": obj.created_at, "updated_at": obj.updated_at}


def _rule_collection(request, kind):
    qs = FeishuConfigRule.objects.filter(tenant=request.user.tenant, kind=kind)
    if request.method == "GET":
        return success_response({"items": [_rule_data(item) for item in qs.order_by("id")]})
    payload = request.data if isinstance(request.data, dict) else {}
    if not payload.get("name") or not payload.get("code"):
        raise ValidationError({"detail": "name and code are required."})
    obj = FeishuConfigRule.objects.create(
        tenant=request.user.tenant, kind=kind, name=payload["name"], code=payload["code"],
        enabled=bool(payload.get("enabled", False)), config=payload.get("config") or {},
        created_by=request.user, updated_by=request.user,
    )
    return success_response(_rule_data(obj), status=201)


def _rule_detail(request, kind, pk):
    obj = get_object_or_404(FeishuConfigRule, pk=pk, tenant=request.user.tenant, kind=kind)
    if request.method == "GET":
        return success_response(_rule_data(obj))
    if request.method == "DELETE":
        obj.delete()
        return success_response({"deleted": True})
    for field in ("name", "code", "enabled", "config"):
        if field in request.data:
            setattr(obj, field, request.data[field])
    obj.updated_by = request.user
    obj.save()
    return success_response(_rule_data(obj))


def _make_rule_views(kind, permission_class):
    @api_view(["GET", "POST"])
    @permission_classes([permission_class])
    def collection(request):
        return _rule_collection(request, kind)

    @api_view(["GET", "PATCH", "DELETE"])
    @permission_classes([permission_class])
    def detail(request, pk):
        return _rule_detail(request, kind, pk)
    return collection, detail


notification_collection, notification_detail = _make_rule_views(FeishuConfigRule.Kind.NOTIFICATION, IsFeishuNotificationUser)
report_collection, report_detail = _make_rule_views(FeishuConfigRule.Kind.REPORT, IsFeishuReportUser)
approval_collection, approval_detail = _make_rule_views(FeishuConfigRule.Kind.APPROVAL, IsFeishuApprovalUser)


@api_view(["GET"])
@permission_classes([IsFeishuOperationsViewer])
def operation_collection(request):
    qs = FeishuOperation.objects.filter(tenant=request.user.tenant)[:200]
    items = [{"id": o.id, "operation_type": o.operation_type, "status": o.status,
              "reference_type": o.reference_type, "reference_id": o.reference_id,
              "masked_detail": o.masked_detail, "error_code": o.error_code,
              "created_at": o.created_at, "updated_at": o.updated_at} for o in qs]
    return success_response({"items": items, "external_calls_enabled": False})
