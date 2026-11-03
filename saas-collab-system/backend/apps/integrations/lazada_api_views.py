from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreViewer, IsIntegrationLiveReadonlyRunner
from .lazada_api_contract import catalog as operation_catalog
from .lazada_api_service import execute_operation, scoped_authorizations, snapshot_data
from .models import LazadaApiSnapshot


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def catalog(request):
    return success_response({"operations":operation_catalog(), "write_enabled":False, "refresh_enabled":False,
        "webhook":"尚未启用外网回调；不能以查询快照冒充Webhook。"})


class OperationInput(serializers.Serializer):
    operation = serializers.CharField(max_length=60)
    payload = serializers.JSONField(default=dict)


@api_view(["GET", "POST"])
@permission_classes([IsMarketplaceStoreViewer, IsIntegrationLiveReadonlyRunner])
def operations(request, pk):
    if request.method == "GET":
        scoped = scoped_authorizations(request.user, execute=True).filter(pk=pk)
        snapshots = LazadaApiSnapshot.objects.filter(authorization__in=scoped, tenant_id=request.user.tenant_id)[:50]
        return success_response([snapshot_data(item) for item in snapshots])
    serializer = OperationInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["operation"] == "smax_sync":
        from .lazada_advertising import sync_advertising
        return success_response(sync_advertising(actor=request.user, authorization_id=pk, payload=data["payload"]))
    return success_response(execute_operation(actor=request.user, authorization_id=pk,
        name=data["operation"], payload=data["payload"]))
