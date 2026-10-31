from django.shortcuts import get_object_or_404
from django.core.paginator import InvalidPage, Paginator
from django.db.models import Q, Subquery
from rest_framework.exceptions import NotFound
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent
from .permissions import (
    IsApprovalReviewer,
    IsApprovalSubmitter,
    IsApprovalViewer,
    IsApprovalWithdrawer,
    IsCollaborationConfirmer,
    IsCollaborationViewer,
    IsExceptionManager,
    IsExceptionViewer,
    filter_permission_scope,
    scope_allows_value,
)
from .serializers import (
    ApprovalMockCreateSerializer,
    ApprovalQuerySerializer,
    ApprovalRequestSerializer,
    AssignSerializer,
    BusinessExceptionSerializer,
    CollaborationEventSerializer,
    CollaborationQuerySerializer,
    DecisionSerializer,
    ExceptionMockCreateSerializer,
    ExceptionQuerySerializer,
    ResolutionSerializer,
)
from .services import (
    assign_exception,
    close_exception,
    create_mock_approval,
    create_mock_exception,
    decide_collaboration_event,
    resolve_exception,
    review_approval,
)


def _page(request, queryset, serializer_class, query):
    paginator = Paginator(queryset, query["page_size"])
    try:
        page_obj = paginator.page(query["page"])
    except InvalidPage as exc:
        raise NotFound("Requested page does not exist.") from exc
    items = list(page_obj.object_list)
    resource_type = {
        ApprovalRequestSerializer: "approval",
        BusinessExceptionSerializer: "exception",
        CollaborationEventSerializer: "collaboration",
    }[serializer_class]
    events_by_resource = {}
    if items:
        events = WorkflowAuditEvent.objects.filter(
            tenant_id=items[0].tenant_id,
            resource_type=resource_type,
            resource_id__in=[str(item.pk) for item in items],
        )
        for event in events:
            events_by_resource.setdefault(event.resource_id, []).append(event)
    payment_requests_by_approval = {}
    if serializer_class is ApprovalRequestSerializer and items:
        from apps.supply_chain.payment_request_models import SupplyPaymentRequest
        payment_requests_by_approval = {r.approval_id: r for r in SupplyPaymentRequest.objects.filter(
            tenant_id=request.user.tenant_id, approval_id__in=[x.pk for x in items]).select_related('payee_account')}
    offset = (query["page"] - 1) * query["page_size"]

    class PageWindow:
        def __len__(self):
            return paginator.count

        def __getitem__(self, key):
            if isinstance(key, slice) and key.start == offset:
                return items[key.start - offset : key.stop - offset]
            return []

    return paginated_data(
        request,
        PageWindow(),
        serializer_class,
        page=query["page"],
        page_size=query["page_size"],
        total_count=paginator.count,
        serializer_context={"audit_events_by_resource": events_by_resource, "request": request,
                            "payment_requests_by_approval": payment_requests_by_approval},
    )


def visible_approvals(user, permission_code="workflow.approvals.view"):
    queryset = ApprovalRequest.objects.filter(tenant=user.tenant).select_related("requested_by", "reviewed_by")
    queryset = filter_permission_scope(user, permission_code, queryset, "approval_type", "approval_types")
    # Keep pagination/count SQL-side while requiring source VIEW scope for payment approvals.
    from apps.permissions.services import check_user_permission
    if not check_user_permission(user, "supply.v2.view"):
        return queryset.exclude(business_type__in=["supply_payment_request", "supply_payment_batch"])
    from apps.supply_chain.models import PurchaseOrder, SupplierShipment, DispatchBatch, InboundOrder
    from apps.supply_chain.permissions import internal_orders, accessible_orders
    from apps.supply_chain.logistics import batches_for
    shipment_orders = accessible_orders(user, PurchaseOrder.objects.all(), "supply.v2.view")
    # business_id is the payment-request id; source_id lives on its related row.
    payment_visible = (~Q(business_type__in=["supply_payment_request", "supply_payment_batch"]) |
        Q(business_type="supply_payment_request", supply_payment_request__kind="purchase", supply_payment_request__source_id__in=Subquery(internal_orders(user, PurchaseOrder.objects.all(), "supply.v2.view").values("pk"))) |
        Q(business_type="supply_payment_request", supply_payment_request__kind__in=["shipment", "domestic_freight"], supply_payment_request__source_id__in=Subquery(SupplierShipment.objects.filter(tenant_id=user.tenant_id, order__in=shipment_orders).values("pk"))) |
        Q(business_type="supply_payment_request", supply_payment_request__kind="batch", supply_payment_request__source_id__in=Subquery(batches_for(user, "supply.v2.view").values("pk"))) |
        Q(business_type="supply_payment_request", supply_payment_request__kind="inbound", supply_payment_request__source_id__in=Subquery(InboundOrder.objects.filter(tenant_id=user.tenant_id, batch__in=batches_for(user, "supply.v2.view")).values("pk"))))
    # Batch approval is visible only when every source line is visible to the reviewer.
    from apps.supply_chain.payment_batches import visible_batches
    return queryset.filter(payment_visible | Q(business_type="supply_payment_batch",
        supply_payment_batch__id__in=Subquery(visible_batches(user).values('pk'))))


def visible_exceptions(user, permission_code="workflow.exceptions.view"):
    queryset = BusinessException.objects.filter(tenant=user.tenant).select_related("assigned_to", "created_by")
    return filter_permission_scope(user, permission_code, queryset, "module", "exception_modules")


def visible_collaboration(user, permission_code="workflow.collaboration.view"):
    queryset = CollaborationEvent.objects.filter(tenant=user.tenant).select_related("confirmed_by")
    return filter_permission_scope(user, permission_code, queryset, "channel", "collaboration_channels")


@api_view(["GET"])
@permission_classes([IsApprovalViewer])
def approval_collection(request):
    serializer = ApprovalQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = visible_approvals(request.user)
    for field in ("approval_type", "status"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_page(request, queryset, ApprovalRequestSerializer, query))


@api_view(["POST"])
@permission_classes([IsApprovalSubmitter])
def approval_mock_create(request):
    serializer = ApprovalMockCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    approval_type = serializer.validated_data["approval_type"]
    if not scope_allows_value(request.user, "workflow.approvals.submit", "approval_types", approval_type):
        raise DataScopeDenied(
            "Approval type is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    approval, created = create_mock_approval(user=request.user, **serializer.validated_data)
    return success_response({"created": created, "approval": ApprovalRequestSerializer(approval, context={"request": request}).data}, status=201 if created else 200)


@api_view(["GET"])
@permission_classes([IsApprovalViewer])
def approval_detail(request, pk):
    return success_response(ApprovalRequestSerializer(get_scoped_object_or_404(visible_approvals(request.user), pk=pk), context={"request": request}).data)


def _approval_action(request, pk, action, permission_code):
    approval = get_scoped_object_or_404(visible_approvals(request.user, permission_code), pk=pk)
    serializer = DecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    approval = review_approval(approval=approval, actor=request.user, action=action, note=serializer.validated_data.get("note", ""))
    return success_response(ApprovalRequestSerializer(approval, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsApprovalReviewer])
def approval_approve(request, pk):
    return _approval_action(request, pk, "approve", "workflow.approvals.review")


@api_view(["POST"])
@permission_classes([IsApprovalReviewer])
def approval_reject(request, pk):
    return _approval_action(request, pk, "reject", "workflow.approvals.review")


@api_view(["POST"])
@permission_classes([IsApprovalWithdrawer])
def approval_withdraw(request, pk):
    return _approval_action(request, pk, "withdraw", "workflow.approvals.withdraw")


@api_view(["GET"])
@permission_classes([IsExceptionViewer])
def exception_collection(request):
    serializer = ExceptionQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = visible_exceptions(request.user)
    for field in ("module", "status"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_page(request, queryset, BusinessExceptionSerializer, query))


@api_view(["POST"])
@permission_classes([IsExceptionManager])
def exception_mock_create(request):
    serializer = ExceptionMockCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    module = serializer.validated_data["module"]
    if not scope_allows_value(request.user, "workflow.exceptions.manage", "exception_modules", module):
        raise PermissionDenied("Exception module is outside the authorized data scope.")
    exception = create_mock_exception(user=request.user, **serializer.validated_data)
    return success_response(BusinessExceptionSerializer(exception).data, status=201)


@api_view(["GET"])
@permission_classes([IsExceptionViewer])
def exception_detail(request, pk):
    return success_response(BusinessExceptionSerializer(get_object_or_404(visible_exceptions(request.user), pk=pk)).data)


def _managed_exception(request, pk):
    return get_object_or_404(visible_exceptions(request.user, "workflow.exceptions.manage"), pk=pk)


@api_view(["POST"])
@permission_classes([IsExceptionManager])
def exception_assign(request, pk):
    serializer = AssignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = assign_exception(exception=_managed_exception(request, pk), actor=request.user, **serializer.validated_data)
    return success_response(BusinessExceptionSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsExceptionManager])
def exception_resolve(request, pk):
    serializer = ResolutionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = resolve_exception(exception=_managed_exception(request, pk), actor=request.user, **serializer.validated_data)
    return success_response(BusinessExceptionSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsExceptionManager])
def exception_close(request, pk):
    item = close_exception(exception=_managed_exception(request, pk), actor=request.user)
    return success_response(BusinessExceptionSerializer(item).data)


@api_view(["GET"])
@permission_classes([IsCollaborationViewer])
def collaboration_collection(request):
    serializer = CollaborationQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = visible_collaboration(request.user)
    for field in ("channel", "status"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_page(request, queryset, CollaborationEventSerializer, query))


def _collaboration_action(request, pk, action):
    item = get_object_or_404(visible_collaboration(request.user, "workflow.collaboration.confirm"), pk=pk)
    serializer = DecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = decide_collaboration_event(event=item, actor=request.user, action=action, note=serializer.validated_data.get("note", ""))
    return success_response(CollaborationEventSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsCollaborationConfirmer])
def collaboration_confirm(request, pk):
    return _collaboration_action(request, pk, "confirm")


@api_view(["POST"])
@permission_classes([IsCollaborationConfirmer])
def collaboration_reject(request, pk):
    return _collaboration_action(request, pk, "reject")
