import hashlib
import secrets

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import (
    IsInternalAPIClientAuditViewer,
    IsInternalAPIClientApprover,
    IsInternalAPIClientReadOrManage,
    IsInternalAPIClientRotator,
)

from .models import InternalAPIClient, InternalAPIClientAudit
from .serializers import InternalAPIClientSerializer


def _new_credential():
    secret = secrets.token_urlsafe(32)
    return secret, make_password(secret), secret[:8], hashlib.sha256(secret.encode()).hexdigest()


def _client_for_request(request, pk, *, lock=False):
    queryset = InternalAPIClient.objects
    if lock:
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=pk, tenant=request.user.tenant)


def _audit(*, request, client, action, detail=None):
    InternalAPIClientAudit.objects.create(
        tenant=request.user.tenant,
        client=client,
        actor=request.user,
        action=action,
        config_version=client.config_version,
        detail=detail or {},
    )


@api_view(["GET", "POST"])
@permission_classes([IsInternalAPIClientReadOrManage])
def client_collection(request):
    if request.method == "GET":
        items = InternalAPIClient.objects.filter(tenant=request.user.tenant)
        return success_response({"items": InternalAPIClientSerializer(items, many=True).data})

    serializer = InternalAPIClientSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    secret, secret_hash, prefix, fingerprint = _new_credential()
    with transaction.atomic():
        client = InternalAPIClient.objects.create(
            tenant=request.user.tenant,
            created_by=request.user,
            updated_by=request.user,
            client_id=f"intapi_{secrets.token_urlsafe(18)}",
            secret_hash=secret_hash,
            secret_prefix=prefix,
            secret_fingerprint=fingerprint,
            last_rotated_at=timezone.now(),
            status=InternalAPIClient.Status.DISABLED,
            approval_status=InternalAPIClient.ApprovalStatus.PENDING,
            **serializer.validated_data,
        )
        _audit(request=request, client=client, action="created", detail={"resources": sorted(client.resources)})
    data = InternalAPIClientSerializer(client).data
    data["client_secret"] = secret
    data["secret_display_once"] = True
    return success_response(data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalAPIClientReadOrManage])
def client_detail(request, pk):
    client = _client_for_request(request, pk)
    if request.method == "GET":
        return success_response(InternalAPIClientSerializer(client).data)
    if "client_id" in request.data or any(key.startswith("secret") for key in request.data):
        raise ValidationError("Client identifiers and secret metadata cannot be updated.")
    serializer = InternalAPIClientSerializer(client, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    changed = sorted(serializer.validated_data)
    with transaction.atomic():
        client = _client_for_request(request, pk, lock=True)
        for key, value in serializer.validated_data.items():
            setattr(client, key, value)
        client.updated_by = request.user
        client.status = InternalAPIClient.Status.DISABLED
        client.approval_status = InternalAPIClient.ApprovalStatus.PENDING
        client.approved_by = None
        client.approved_at = None
        client.reviewed_at = None
        client.rejection_reason = ""
        client.config_version += 1
        client.save()
        _audit(request=request, client=client, action="updated", detail={"changed_fields": changed})
    return success_response(InternalAPIClientSerializer(client).data)


@api_view(["POST"])
@permission_classes([IsInternalAPIClientReadOrManage])
def client_status(request, pk):
    status = request.data.get("status") if isinstance(request.data, dict) else None
    if status not in InternalAPIClient.Status.values:
        raise ValidationError({"status": "Must be active or disabled."})
    with transaction.atomic():
        client = _client_for_request(request, pk, lock=True)
        if status == InternalAPIClient.Status.ACTIVE and client.approval_status != InternalAPIClient.ApprovalStatus.APPROVED:
            raise ValidationError({"status": "审批通过后才能启用调用方。"})
        if client.status != status:
            client.status = status
            client.updated_by = request.user
            client.config_version += 1
            client.save(update_fields=["status", "updated_by", "config_version", "updated_at"])
            _audit(request=request, client=client, action=status)
    return success_response(InternalAPIClientSerializer(client).data)


@api_view(["POST"])
@permission_classes([IsInternalAPIClientApprover])
def client_review(request, pk):
    decision = request.data.get("decision") if isinstance(request.data, dict) else None
    reason = str(request.data.get("reason") or "").strip() if isinstance(request.data, dict) else ""
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Must be approve or reject."})
    if decision == "reject" and not reason:
        raise ValidationError({"reason": "拒绝时必须填写原因。"})
    if len(reason) > 500:
        raise ValidationError({"reason": "Must be at most 500 characters."})
    with transaction.atomic():
        client = _client_for_request(request, pk, lock=True)
        if client.created_by_id == request.user.id or client.updated_by_id == request.user.id:
            raise ValidationError({"decision": "创建或修改配置的人不能审核自己的配置。"})
        if client.approval_status != InternalAPIClient.ApprovalStatus.PENDING:
            raise ValidationError({"decision": "Only pending configurations can be reviewed."})
        client.approval_status = (InternalAPIClient.ApprovalStatus.APPROVED if decision == "approve"
                                  else InternalAPIClient.ApprovalStatus.REJECTED)
        client.approved_by = request.user if decision == "approve" else None
        client.approved_at = timezone.now() if decision == "approve" else None
        client.reviewed_at = timezone.now()
        client.rejection_reason = reason if decision == "reject" else ""
        client.status = InternalAPIClient.Status.DISABLED
        client.config_version += 1
        client.save()
        _audit(request=request, client=client, action="approved" if decision == "approve" else "rejected", detail={"reason": reason})
    return success_response(InternalAPIClientSerializer(client).data)


@api_view(["POST"])
@permission_classes([IsInternalAPIClientRotator])
def client_rotate(request, pk):
    operation_id = request.headers.get("Idempotency-Key") or (
        request.data.get("operation_id") if isinstance(request.data, dict) else None
    )
    if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200:
        raise ValidationError({"operation_id": "A non-empty Idempotency-Key is required."})
    operation_hash = hashlib.sha256(operation_id.strip().encode()).hexdigest()
    with transaction.atomic():
        client = _client_for_request(request, pk, lock=True)
        if secrets.compare_digest(client.last_rotation_operation_hash, operation_hash):
            data = InternalAPIClientSerializer(client).data
            data.update({"rotated": False, "idempotent_replay": True, "client_secret": None})
            return success_response(data)
        secret, secret_hash, prefix, fingerprint = _new_credential()
        client.secret_hash = secret_hash
        client.secret_prefix = prefix
        client.secret_fingerprint = fingerprint
        client.last_rotated_at = timezone.now()
        client.last_rotation_operation_hash = operation_hash
        client.updated_by = request.user
        client.config_version += 1
        client.save()
        _audit(request=request, client=client, action="secret_rotated")
    data = InternalAPIClientSerializer(client).data
    data.update({"rotated": True, "idempotent_replay": False, "client_secret": secret, "secret_display_once": True})
    return success_response(data)


@api_view(["GET"])
@permission_classes([IsInternalAPIClientAuditViewer])
def client_audit(request, pk):
    client = _client_for_request(request, pk)
    items = [
        {
            "id": item.id,
            "action": item.action,
            "actor_id": item.actor_id,
            "actor_name": item.actor.username,
            "config_version": item.config_version,
            "detail": item.detail,
            "created_at": item.created_at,
        }
        for item in client.audit_logs.select_related("actor")
    ]
    return success_response({"items": items})
