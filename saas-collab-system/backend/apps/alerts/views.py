from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.models import CustomUser
from apps.common.responses import success_response
from apps.products.models import ProductSKU, ProductSPU

from .business_services import assign_business_alert, close_business_alert, evaluate_business_alert, silence_business_alert
from .models import BusinessAlert, BusinessAlertRule, InventoryAlert, InventoryAlertRule
from .permissions import (
    IsAlertEvaluator,
    IsAlertManager,
    IsAlertViewer,
    filter_business_alerts,
    filter_inventory_alerts,
)
from .serializers import (
    BusinessAlertAssignSerializer,
    BusinessAlertCloseSerializer,
    BusinessAlertEvaluationSerializer,
    BusinessAlertQuerySerializer,
    BusinessAlertSerializer,
    BusinessAlertSilenceSerializer,
    InventoryAlertAssignSerializer,
    InventoryAlertCloseSerializer,
    InventoryAlertEvaluationSerializer,
    InventoryAlertQuerySerializer,
    InventoryAlertSerializer,
    InventoryAlertSilenceSerializer,
)
from .services import assign_inventory_alert, close_inventory_alert, evaluate_inventory_alert, silence_inventory_alert


def _alert_queryset(request):
    return filter_inventory_alerts(
        request.user,
        InventoryAlert.objects.select_related("rule", "spu", "sku", "assigned_to").prefetch_related("events"),
    )


@api_view(["GET"])
@permission_classes([IsAlertViewer])
def inventory_alert_list(request):
    serializer = InventoryAlertQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = _alert_queryset(request)
    for field in ("status", "alert_type", "severity"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    paginator = Paginator(queryset, query["page_size"])
    if query["page"] > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page = paginator.page(query["page"])
    return success_response(
        {
            "items": InventoryAlertSerializer(page.object_list, many=True).data,
            "pagination": {
                "page": page.number,
                "page_size": query["page_size"],
                "total": paginator.count,
                "total_pages": paginator.num_pages,
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAlertViewer])
def inventory_alert_detail(request, pk):
    return success_response(InventoryAlertSerializer(get_object_or_404(_alert_queryset(request), pk=pk)).data)


@api_view(["POST"])
@permission_classes([IsAlertEvaluator])
def inventory_alert_evaluate_mock(request):
    serializer = InventoryAlertEvaluationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    rule = get_object_or_404(InventoryAlertRule, pk=values.pop("rule_id"), tenant=request.user.tenant)
    sku_id = values.pop("sku_id", None)
    spu_id = values.pop("spu_id", None)
    sku = get_object_or_404(ProductSKU, pk=sku_id, tenant=request.user.tenant) if sku_id else None
    spu = get_object_or_404(ProductSPU, pk=spu_id, tenant=request.user.tenant) if spu_id else None
    alert, created = evaluate_inventory_alert(tenant=request.user.tenant, rule=rule, sku=sku, spu=spu, **values)
    data = {"alert": InventoryAlertSerializer(alert).data if alert else None, "created": created, "mode": "mock"}
    return success_response(data, status=201 if created else 200)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_assign(request, pk):
    serializer = InventoryAlertAssignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request), pk=pk)
    assignee = get_object_or_404(
        CustomUser,
        pk=serializer.validated_data["assigned_to_id"],
        tenant=request.user.tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_active=True,
    )
    return success_response(InventoryAlertSerializer(assign_inventory_alert(alert=alert, actor=request.user, assignee=assignee)).data)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_silence(request, pk):
    serializer = InventoryAlertSilenceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request), pk=pk)
    return success_response(
        InventoryAlertSerializer(
            silence_inventory_alert(alert=alert, actor=request.user, minutes=serializer.validated_data.get("minutes"))
        ).data
    )


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_close(request, pk):
    serializer = InventoryAlertCloseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request), pk=pk)
    return success_response(
        InventoryAlertSerializer(
            close_inventory_alert(alert=alert, actor=request.user, reason=serializer.validated_data["reason"])
        ).data
    )


def _business_alert_queryset(request):
    return filter_business_alerts(
        request.user,
        BusinessAlert.objects.select_related("rule", "assigned_to").prefetch_related("action_logs"),
    )


@api_view(["GET"])
@permission_classes([IsAlertViewer])
def business_alert_list(request):
    serializer = BusinessAlertQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = _business_alert_queryset(request)
    for field in ("status", "severity", "business_type"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    paginator = Paginator(queryset, query["page_size"])
    if query["page"] > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page = paginator.page(query["page"])
    return success_response({
        "items": BusinessAlertSerializer(page.object_list, many=True).data,
        "pagination": {
            "page": page.number,
            "page_size": query["page_size"],
            "total": paginator.count,
            "total_pages": paginator.num_pages,
        },
    })


@api_view(["GET"])
@permission_classes([IsAlertViewer])
def business_alert_detail(request, pk):
    return success_response(BusinessAlertSerializer(get_object_or_404(_business_alert_queryset(request), pk=pk)).data)


@api_view(["POST"])
@permission_classes([IsAlertEvaluator])
def business_alert_evaluate_mock(request):
    serializer = BusinessAlertEvaluationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    rule = get_object_or_404(BusinessAlertRule, pk=values.pop("rule_id"), tenant=request.user.tenant)
    alert, created = evaluate_business_alert(tenant=request.user.tenant, rule=rule, **values)
    return success_response(
        {"alert": BusinessAlertSerializer(alert).data if alert else None, "created": created, "mode": "mock"},
        status=201 if created else 200,
    )


@api_view(["POST"])
@permission_classes([IsAlertManager])
def business_alert_assign(request, pk):
    serializer = BusinessAlertAssignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_business_alert_queryset(request), pk=pk)
    assignee = get_object_or_404(
        CustomUser,
        pk=serializer.validated_data["assigned_to_id"],
        tenant=request.user.tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_active=True,
    )
    alert = assign_business_alert(
        alert=alert,
        actor=request.user,
        assignee=assignee,
        note=serializer.validated_data["note"],
    )
    return success_response(BusinessAlertSerializer(alert).data)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def business_alert_silence(request, pk):
    serializer = BusinessAlertSilenceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_business_alert_queryset(request), pk=pk)
    alert = silence_business_alert(
        alert=alert,
        actor=request.user,
        minutes=serializer.validated_data.get("minutes"),
        note=serializer.validated_data["note"],
    )
    return success_response(BusinessAlertSerializer(alert).data)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def business_alert_close(request, pk):
    serializer = BusinessAlertCloseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_business_alert_queryset(request), pk=pk)
    alert = close_business_alert(alert=alert, actor=request.user, note=serializer.validated_data["note"])
    return success_response(BusinessAlertSerializer(alert).data)
