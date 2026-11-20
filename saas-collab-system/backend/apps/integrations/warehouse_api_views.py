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
    provider = serializers.ChoiceField(choices=["jifeng_wms", "best_ecapi"], default="jifeng_wms")
    operation = serializers.CharField(max_length=60)
    payload = serializers.JSONField()
    confirmed = serializers.BooleanField(default=False)
    idempotency_key = serializers.CharField(required=False, default="", max_length=120, trim_whitespace=False)


@api_view(["GET"])
@permission_classes([IsWarehouseAuthorizationViewer])
def catalog(request):
    provider = serializers.ChoiceField(choices=["jifeng_wms", "best_ecapi"]).run_validation(request.query_params.get("provider", "jifeng_wms"))
    if provider == "best_ecapi":
        from .best_glink import OPERATIONS as best_operations
        from .best_glink_contract import CONTRACTS, CALLBACKS, request_template
        return success_response({"source": "https://open.qianyierp.com/zh-CN/WMS/WMS-reference.html", "provider": provider,
            "operations": [{**asdict(op), "module": CONTRACTS[op.name]["module"],
                "fields": CONTRACTS[op.name]["fields"], "template": request_template(op.name),
                "source": CONTRACTS[op.name]["source"]} for op in best_operations], "live_verified": False,
            "callbacks": [{"name": name, "label": item["label"], "module": item["module"], "source": item["source"]}
                          for name, item in CALLBACKS.items()],
            "callbacks_enabled": bool(getattr(settings, "BEST_GLINK_CALLBACKS_ENABLED", False)),
            "execution_enabled": (getattr(settings, "BEST_ECAPI_ENABLED", False) is True
                                  and getattr(settings, "WAREHOUSE_BUSINESS_API_ENABLED", False) is True),
            "write_enabled": getattr(settings, "WAREHOUSE_BUSINESS_WRITE_ENABLED", False) is True})
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
    if data["provider"] == "best_ecapi":
        from .best_glink import prepare_operation as best_prepare
        return success_response(best_prepare(data["operation"], data["payload"]))
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


@api_view(["GET"])
@permission_classes([IsWarehouseAuthorizationViewer])
def best_notifications(request, pk):
    from rest_framework.exceptions import PermissionDenied
    from apps.permissions.ui_p6_scopes import integration_values_allowed
    from .best_glink_contract import CALLBACKS
    from .models import WebhookEvent
    from .raw_services import load_raw_payload
    from .warehouse_api_service import _redact
    record = get_scoped_object_or_404(WarehouseAuthorization.objects.select_related("integration_config")
        .filter(tenant_id=request.user.tenant_id, provider="best_ecapi"), pk=pk)
    if not integration_values_allowed(request.user, "integrations.warehouse.view", platform="best_ecapi",
            regions=[record.external_warehouse_region], config_id=record.integration_config_id,
            warehouse_id=record.warehouse_id, environment=record.integration_config.environment):
        raise PermissionDenied("仓库反馈不在当前查看范围内。")
    types = {f"best:{record.pk}:{name}": item for name, item in CALLBACKS.items()}
    events = WebhookEvent.objects.filter(tenant_id=record.tenant_id, platform="best_ecapi", event_type__in=types)
    event_id = request.query_params.get("event_id")
    if event_id:
        event = get_scoped_object_or_404(events.select_related("raw_envelope"), pk=event_id)
        return success_response({"id": event.pk, "data": _redact(load_raw_payload(event.raw_envelope)),
            "business_posted": False})
    return success_response({"results": [{"id": event.pk, "name": event.event_type.split(":", 2)[2],
        "label": types[event.event_type]["label"], "received_at": event.received_at,
        "status": "已验签接收，未自动入账"} for event in events[:50]],
        "callbacks_enabled": bool(getattr(settings, "BEST_GLINK_CALLBACKS_ENABLED", False))})
