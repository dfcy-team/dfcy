"""Warehouse catalog and offline preview remain usable without credentials."""
from dataclasses import asdict

from django.conf import settings
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.exceptions import get_scoped_object_or_404
from apps.common.responses import success_response
from apps.permissions.api_permissions import IsWarehouseAuthorizationViewer
from .models import WarehouseAuthorization
from .warehouse_api_contract import OPERATIONS, prepare_operation
from .warehouse_api_service import execute_operation


class OperationInput(serializers.Serializer):
    operation = serializers.CharField(max_length=60)
    payload = serializers.JSONField()
    confirmed = serializers.BooleanField(default=False)
    idempotency_key = serializers.CharField(required=False, default="", max_length=120, trim_whitespace=False)


@api_view(["GET"])
@permission_classes([IsWarehouseAuthorizationViewer])
def catalog(request):
    return success_response({
        "source": "https://app.apifox.com/project/3972134", "contract_date": "2026-10-26",
        "operations": [asdict(operation) for operation in OPERATIONS],
        "oauth": "使用现有仓库首次授权及刷新流程，不通过业务接口转发OAuth凭据。",
        "execution_enabled": getattr(settings, "WAREHOUSE_BUSINESS_API_ENABLED", False) is True,
        "write_enabled": getattr(settings, "WAREHOUSE_BUSINESS_WRITE_ENABLED", False) is True,
        "live_verified": False,
    })


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationViewer])
def preview(request):
    serializer = OperationInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    return success_response(prepare_operation(data["operation"], data["payload"]))


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationViewer])
def execute(request, pk):
    serializer = OperationInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    record = get_scoped_object_or_404(WarehouseAuthorization.objects.select_related(
        "integration_config", "warehouse").filter(tenant_id=request.user.tenant_id), pk=pk)
    data = serializer.validated_data
    return success_response(execute_operation(actor=request.user, authorization=record,
        name=data["operation"], payload=data["payload"], confirmed=data["confirmed"],
        idempotency_key=data["idempotency_key"]))
