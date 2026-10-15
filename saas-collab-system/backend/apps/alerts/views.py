from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.models import CustomUser
from apps.common.data_scope import custom_scope_allows, custom_scope_allows_product
from apps.common.responses import paginated_data, success_response
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
    InventoryAlertFollowUpSerializer,
    InventoryAlertQuerySerializer,
    InventoryAlertSerializer,
    InventoryAlertSilenceSerializer,
)
from .services import assign_inventory_alert, close_inventory_alert, evaluate_inventory_alert, silence_inventory_alert, update_inventory_alert_follow_up


def _alert_queryset(request, permission_code="alerts.view"):
    return filter_inventory_alerts(
        request.user,
        InventoryAlert.objects.select_related("rule", "spu", "sku", "assigned_to").prefetch_related("events"),
        permission_code=permission_code,
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
    return success_response(
        paginated_data(request, queryset, InventoryAlertSerializer, page=query["page"], page_size=query["page_size"])
    )


@api_view(["GET"])
@permission_classes([IsAlertViewer])
def inventory_alert_detail(request, pk):
    return success_response(InventoryAlertSerializer(get_object_or_404(_alert_queryset(request), pk=pk)).data)


@api_view(["GET"])
@permission_classes([IsAlertManager])
def inventory_alert_assignees(request):
    # Require access to at least one manageable alert before exposing tenant coworkers.
    if not _alert_queryset(request, "alerts.manage").exists():
        return success_response([])
    people = CustomUser.objects.filter(
        tenant=request.user.tenant, user_type=CustomUser.UserType.INTERNAL, is_active=True,
    ).only("id", "full_name", "username").order_by("full_name", "username")
    return success_response([{"id": person.id, "name": person.full_name or person.username} for person in people])


@api_view(["PATCH"])
@permission_classes([IsAlertManager])
def inventory_alert_follow_up(request, pk):
    serializer = InventoryAlertFollowUpSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    alert = get_object_or_404(_alert_queryset(request, "alerts.manage"), pk=pk)
    assignee = None
    if "assigned_to_id" in values and values["assigned_to_id"] is not None:
        assignee = get_object_or_404(
            CustomUser, pk=values["assigned_to_id"], tenant=request.user.tenant,
            user_type=CustomUser.UserType.INTERNAL, is_active=True,
        )
    service_values = {key: value for key, value in values.items() if key not in {"expected_version", "assigned_to_id"}}
    if "assigned_to_id" in values:
        service_values["assigned_to"] = assignee
    alert = update_inventory_alert_follow_up(
        alert=alert, actor=request.user, expected_version=values["expected_version"], values=service_values,
    )
    return success_response(InventoryAlertSerializer(alert).data)


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
    if not custom_scope_allows_product(
        request.user,
        sku=sku,
        spu=spu,
        extra_constraints={"warehouse_codes": values.get("warehouse_code", "")},
        permission_code="alerts.evaluate",
    ):
        raise PermissionDenied("Inventory alert target is outside the authorized data scope.")
    alert, created = evaluate_inventory_alert(tenant=request.user.tenant, rule=rule, sku=sku, spu=spu, **values)
    data = {"alert": InventoryAlertSerializer(alert).data if alert else None, "created": created, "mode": "mock"}
    return success_response(data, status=201 if created else 200)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_assign(request, pk):
    serializer = InventoryAlertAssignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request, "alerts.manage"), pk=pk)
    assignee = get_object_or_404(
        CustomUser,
        pk=serializer.validated_data["assigned_to_id"],
        tenant=request.user.tenant,
        user_type=CustomUser.UserType.INTERNAL,
        is_active=True,
    )
    return success_response(InventoryAlertSerializer(assign_inventory_alert(alert=alert, actor=request.user, assignee=assignee, expected_version=serializer.validated_data.get("expected_version"))).data)


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_silence(request, pk):
    serializer = InventoryAlertSilenceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request, "alerts.manage"), pk=pk)
    return success_response(
        InventoryAlertSerializer(
            silence_inventory_alert(alert=alert, actor=request.user, minutes=serializer.validated_data.get("minutes"), expected_version=serializer.validated_data.get("expected_version"))
        ).data
    )


@api_view(["POST"])
@permission_classes([IsAlertManager])
def inventory_alert_close(request, pk):
    serializer = InventoryAlertCloseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    alert = get_object_or_404(_alert_queryset(request, "alerts.manage"), pk=pk)
    return success_response(
        InventoryAlertSerializer(
            close_inventory_alert(alert=alert, actor=request.user, reason=serializer.validated_data["reason"], expected_version=serializer.validated_data.get("expected_version"))
        ).data
    )


def _business_alert_queryset(request, permission_code="alerts.view"):
    return filter_business_alerts(
        request.user,
        BusinessAlert.objects.select_related("rule", "assigned_to").prefetch_related("action_logs"),
        permission_code=permission_code,
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
    return success_response(
        paginated_data(request, queryset, BusinessAlertSerializer, page=query["page"], page_size=query["page_size"])
    )


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
    if not custom_scope_allows(
        request.user,
        {
            "business_types": values["business_type"],
            "business_ids": values["business_id"],
        },
        permission_code="alerts.evaluate",
    ):
        raise PermissionDenied("Business alert target is outside the authorized data scope.")
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
    alert = get_object_or_404(_business_alert_queryset(request, "alerts.manage"), pk=pk)
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
    alert = get_object_or_404(_business_alert_queryset(request, "alerts.manage"), pk=pk)
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
    alert = get_object_or_404(_business_alert_queryset(request, "alerts.manage"), pk=pk)
    alert = close_business_alert(alert=alert, actor=request.user, note=serializer.validated_data["note"])
    return success_response(BusinessAlertSerializer(alert).data)
