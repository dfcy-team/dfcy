from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.accounts.miniapp_permissions import IsMiniAppToken
from apps.common.exceptions import ScopedResourceNotFound
from apps.purchasing.models import SupplyPurchaseOrder

from .api_idempotency import (
    execute_json_action,
    execute_label_action,
    idempotency_key,
)
from .labels import create_label_snapshot, render_label_pdf
from .models import (
    PackingApiIdempotencyRecord,
    PackingBatch,
    PackingBox,
    PackingChangeRequest,
    PackingStandardVersion,
)
from .permissions import (
    IsNonMiniAppChannel,
    filter_internal_batches,
    filter_supplier_batches,
    require_internal_permission,
    require_supplier_capability,
    resolve_create_orders,
    supplier_id_for_user,
)
from .representations import (
    batch_detail_data,
    batch_summary_data,
    change_request_data,
    standard_data,
)
from .serializers import (
    ExpectedVersionSerializer,
    PackingBatchCreateSerializer,
    PackingBoxWriteSerializer,
    PackingChangeSubmitSerializer,
    PackingLabelSerializer,
    PackingReviewSerializer,
)
from .services import (
    add_packing_box,
    approve_packing_change,
    cancel_packing_batch,
    complete_packing_batch,
    create_packing_batch,
    reject_packing_change,
    remove_packing_box,
    replace_packing_box,
    submit_packing_change,
)


INTERNAL = PackingApiIdempotencyRecord.Channel.INTERNAL
SUPPLIER_WEB = PackingApiIdempotencyRecord.Channel.SUPPLIER_WEB
MINIAPP = PackingApiIdempotencyRecord.Channel.MINIAPP


def _batch_queryset():
    return (
        PackingBatch.objects.select_related(
            "tenant",
            "supplier",
            "standard_version",
            "created_by",
        )
        .prefetch_related(
            "batch_orders__order__lines",
            "boxes__items",
        )
    )


def _change_queryset():
    return PackingChangeRequest.objects.select_related(
        "batch",
        "submitted_by",
        "reviewed_by",
    )


def _positive_query(value, field):
    if value in (None, ""):
        return None
    if not str(value).isdigit() or int(value) < 1:
        raise ValidationError({field: "A positive integer is required."})
    return int(value)


def _strict_query(request, allowed):
    unknown = set(request.query_params) - set(allowed)
    if unknown:
        raise ValidationError({"unknown_query": f"Unknown query parameters: {sorted(unknown)}"})


def _page_values(request):
    page = _positive_query(request.query_params.get("page"), "page") or 1
    page_size = _positive_query(request.query_params.get("page_size"), "page_size") or 20
    if page_size > 100:
        raise ValidationError({"page_size": "page_size must not exceed 100."})
    return page, page_size


def _paginated(request, queryset, transform):
    page, page_size = _page_values(request)
    paginator = Paginator(queryset, page_size)
    if page > paginator.num_pages:
        raise ScopedResourceNotFound("Requested page does not exist.")
    page_obj = paginator.page(page)

    def url(number):
        if number is None:
            return None
        params = request.query_params.copy()
        params["page"] = number
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return {
        "count": paginator.count,
        "next": url(page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        "results": [transform(item) for item in page_obj.object_list],
    }


def _success(data, status=200):
    from apps.common.responses import success_response

    return success_response(data, status=status)


def _filter_batches(request, queryset, *, internal):
    allowed = {
        "search",
        "status",
        "order_id",
        "created_at_from",
        "created_at_to",
        "page",
        "page_size",
    }
    if internal:
        allowed.add("supplier_id")
    _strict_query(request, allowed)
    search = request.query_params.get("search", "").strip()
    if len(search) > 100:
        raise ValidationError({"search": "Search must not exceed 100 characters."})
    if search:
        queryset = queryset.filter(
            Q(batch_no__icontains=search)
            | Q(batch_orders__order__order_no__icontains=search)
            | Q(supplier__code__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(boxes__items__sku_code_snapshot__icontains=search)
        ).distinct()
    status = request.query_params.get("status", "").strip()
    if status:
        if status not in PackingBatch.Status.values:
            raise ValidationError({"status": "Packing batch status is invalid."})
        queryset = queryset.filter(status=status)
    supplier_id = _positive_query(request.query_params.get("supplier_id"), "supplier_id")
    order_id = _positive_query(request.query_params.get("order_id"), "order_id")
    if supplier_id:
        queryset = queryset.filter(supplier_id=supplier_id)
    if order_id:
        queryset = queryset.filter(batch_orders__order_id=order_id)
    start = request.query_params.get("created_at_from")
    end = request.query_params.get("created_at_to")
    start_value = parse_datetime(start) if start else None
    end_value = parse_datetime(end) if end else None
    if start and start_value is None:
        raise ValidationError({"created_at_from": "A valid ISO-8601 datetime is required."})
    if end and end_value is None:
        raise ValidationError({"created_at_to": "A valid ISO-8601 datetime is required."})
    if start_value and end_value and start_value > end_value:
        raise ValidationError({"created_at_from": "created_at_from must not exceed created_at_to."})
    if start_value:
        queryset = queryset.filter(created_at__gte=start_value)
    if end_value:
        queryset = queryset.filter(created_at__lte=end_value)
    return queryset


def _authorized_batches(request, permission_code, *, internal):
    queryset = _batch_queryset()
    if internal:
        return filter_internal_batches(request.user, queryset, permission_code)
    return filter_supplier_batches(request.user, queryset)


def _get_batch(request, pk, permission_code, *, internal):
    batch = _authorized_batches(request, permission_code, internal=internal).filter(pk=pk).first()
    if batch is None:
        raise ScopedResourceNotFound("Packing batch is not available in the authorized scope.")
    return batch


def _require_supplier_write(user, batch):
    require_supplier_capability(
        user,
        batch.supplier_id,
        mixed_orders=batch.batch_orders.count() > 1,
    )


def _batch_collection(request, *, channel, internal):
    if request.method == "GET":
        queryset = _authorized_batches(
            request,
            "supply.packing.view",
            internal=internal,
        )
        queryset = _filter_batches(request, queryset, internal=internal)
        return _success(
            _paginated(request, queryset, batch_summary_data)
        )

    serializer = PackingBatchCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    if internal:
        resolve_create_orders(request.user, payload["order_ids"])
    else:
        supplier_id = supplier_id_for_user(request.user)
        orders = list(
            SupplyPurchaseOrder.objects.filter(
                tenant=request.user.tenant,
                pk__in=payload["order_ids"],
                supplier_id=supplier_id,
            )
        )
        if len(orders) != len(payload["order_ids"]):
            raise ScopedResourceNotFound("Purchase orders are not available for this supplier.")
        require_supplier_capability(
            request.user,
            supplier_id,
            mixed_orders=len(payload["order_ids"]) > 1,
        )

    def callback(key):
        batch, _ = create_packing_batch(
            order_ids=payload["order_ids"],
            actor=request.user,
            idempotency_key=key,
            note=payload.get("note", ""),
        )
        batch_id = batch.id
        current = _batch_queryset().get(pk=batch_id)
        return batch_detail_data(current, internal=internal), 201

    return execute_json_action(
        request,
        channel=channel,
        action="create_batch",
        scope_key="packing:batches:collection",
        resource_key="packing:batches:collection",
        payload=payload,
        callback=callback,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_batch_collection(request):
    if request.method == "POST":
        require_internal_permission(request.user, "supply.packing.create")
    return _batch_collection(request, channel=INTERNAL, internal=True)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_batch_collection(request):
    supplier_id_for_user(request.user)
    return _batch_collection(request, channel=SUPPLIER_WEB, internal=False)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_batch_collection(request):
    supplier_id_for_user(request.user)
    return _batch_collection(request, channel=MINIAPP, internal=False)


def _batch_detail(request, pk, *, internal):
    return _success(
        batch_detail_data(
            _get_batch(request, pk, "supply.packing.view", internal=internal),
            internal=internal,
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_batch_detail(request, pk):
    return _batch_detail(request, pk, internal=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_batch_detail(request, pk):
    return _batch_detail(request, pk, internal=False)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_batch_detail(request, pk):
    return _batch_detail(request, pk, internal=False)


def _box_write(request, pk, *, channel, internal, box_id=None):
    batch = _get_batch(request, pk, "supply.packing.manage", internal=internal)
    if not internal:
        _require_supplier_write(request.user, batch)
    serializer = PackingBoxWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    action = "add_box" if box_id is None else "update_box"
    scope_key = f"packing:batch:{pk}" if box_id is None else f"packing:box:{box_id}"
    resource_key = scope_key

    def callback(key):
        kwargs = {
            "batch_id": pk,
            "actor": request.user,
            "idempotency_key": key,
            **payload,
        }
        if box_id is None:
            add_packing_box(**kwargs)
            status = 201
        else:
            replace_packing_box(box_id=box_id, **kwargs)
            status = 200
        current = _batch_queryset().get(pk=pk)
        return batch_detail_data(current, internal=internal), status

    return execute_json_action(
        request,
        channel=channel,
        action=action,
        scope_key=scope_key,
        resource_key=resource_key,
        payload=payload,
        callback=callback,
    )


def _expected_action(
    request,
    pk,
    *,
    channel,
    internal,
    action,
    permission_code,
    service,
    box_id=None,
):
    batch = _get_batch(request, pk, permission_code, internal=internal)
    if not internal:
        _require_supplier_write(request.user, batch)
    serializer = ExpectedVersionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    scope_key = f"packing:box:{box_id}" if box_id else f"packing:batch:{pk}"

    def callback(key):
        kwargs = {
            "batch_id": pk,
            "actor": request.user,
            "idempotency_key": key,
            **payload,
        }
        if box_id:
            kwargs["box_id"] = box_id
        service(**kwargs)
        current = _batch_queryset().get(pk=pk)
        return batch_detail_data(current, internal=internal), 200

    return execute_json_action(
        request,
        channel=channel,
        action=action,
        scope_key=scope_key,
        resource_key=scope_key,
        payload=payload,
        callback=callback,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_box_collection(request, pk):
    return _box_write(request, pk, channel=INTERNAL, internal=True)


@api_view(["PUT"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_box_detail(request, pk, box_id):
    return _box_write(request, pk, channel=INTERNAL, internal=True, box_id=box_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_box_remove(request, pk, box_id):
    return _expected_action(
        request,
        pk,
        channel=INTERNAL,
        internal=True,
        action="remove_box",
        permission_code="supply.packing.manage",
        service=remove_packing_box,
        box_id=box_id,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_box_collection(request, pk):
    return _box_write(request, pk, channel=SUPPLIER_WEB, internal=False)


@api_view(["PUT"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_box_detail(request, pk, box_id):
    return _box_write(request, pk, channel=SUPPLIER_WEB, internal=False, box_id=box_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_box_remove(request, pk, box_id):
    return _expected_action(
        request,
        pk,
        channel=SUPPLIER_WEB,
        internal=False,
        action="remove_box",
        permission_code="supply.packing.manage",
        service=remove_packing_box,
        box_id=box_id,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_box_collection(request, pk):
    return _box_write(request, pk, channel=MINIAPP, internal=False)


@api_view(["PUT"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_box_detail(request, pk, box_id):
    return _box_write(request, pk, channel=MINIAPP, internal=False, box_id=box_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_box_remove(request, pk, box_id):
    return _expected_action(
        request,
        pk,
        channel=MINIAPP,
        internal=False,
        action="remove_box",
        permission_code="supply.packing.manage",
        service=remove_packing_box,
        box_id=box_id,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_batch_complete(request, pk):
    return _expected_action(
        request,
        pk,
        channel=INTERNAL,
        internal=True,
        action="complete_batch",
        permission_code="supply.packing.complete",
        service=complete_packing_batch,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_batch_cancel(request, pk):
    return _expected_action(
        request,
        pk,
        channel=INTERNAL,
        internal=True,
        action="cancel_batch",
        permission_code="supply.packing.manage",
        service=cancel_packing_batch,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_batch_complete(request, pk):
    return _expected_action(
        request,
        pk,
        channel=SUPPLIER_WEB,
        internal=False,
        action="complete_batch",
        permission_code="supply.packing.complete",
        service=complete_packing_batch,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_batch_complete(request, pk):
    return _expected_action(
        request,
        pk,
        channel=MINIAPP,
        internal=False,
        action="complete_batch",
        permission_code="supply.packing.complete",
        service=complete_packing_batch,
    )


def _change_collection(request, pk, *, channel, internal):
    batch = _get_batch(
        request,
        pk,
        "supply.packing.view" if request.method == "GET" else "supply.packing.manage",
        internal=internal,
    )
    if request.method == "GET":
        _strict_query(request, {"status", "page", "page_size"})
        queryset = _change_queryset().filter(batch=batch)
        status = request.query_params.get("status", "")
        if status:
            if status not in PackingChangeRequest.Status.values:
                raise ValidationError({"status": "Change-request status is invalid."})
            queryset = queryset.filter(status=status)
        return _success(
            _paginated(
                request,
                queryset,
                lambda item: change_request_data(item, internal=internal),
            )
        )
    if not internal:
        _require_supplier_write(request.user, batch)
    serializer = PackingChangeSubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    scope_key = f"packing:batch:{pk}:change-requests"

    def callback(key):
        change, _, _ = submit_packing_change(
            batch_id=pk,
            actor=request.user,
            idempotency_key=key,
            **payload,
        )
        current = _change_queryset().get(pk=change.id)
        return change_request_data(current, internal=internal), 201

    return execute_json_action(
        request,
        channel=channel,
        action="submit_change",
        scope_key=scope_key,
        resource_key=scope_key,
        payload=payload,
        callback=callback,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_change_collection(request, pk):
    return _change_collection(request, pk, channel=INTERNAL, internal=True)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_change_collection(request, pk):
    return _change_collection(request, pk, channel=SUPPLIER_WEB, internal=False)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_change_collection(request, pk):
    return _change_collection(request, pk, channel=MINIAPP, internal=False)


def _review_queryset(request):
    scoped_batches = filter_internal_batches(
        request.user,
        PackingBatch.objects.all(),
        "supply.packing.change.review",
    )
    return _change_queryset().filter(
        tenant=request.user.tenant,
        batch_id__in=scoped_batches.values("pk"),
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_review_collection(request):
    _strict_query(request, {"status", "batch_id", "supplier_id", "page", "page_size"})
    queryset = _review_queryset(request)
    status = request.query_params.get("status", "")
    if status:
        if status not in PackingChangeRequest.Status.values:
            raise ValidationError({"status": "Change-request status is invalid."})
        queryset = queryset.filter(status=status)
    batch_id = _positive_query(request.query_params.get("batch_id"), "batch_id")
    supplier_id = _positive_query(request.query_params.get("supplier_id"), "supplier_id")
    if batch_id:
        queryset = queryset.filter(batch_id=batch_id)
    if supplier_id:
        queryset = queryset.filter(batch__supplier_id=supplier_id)
    return _success(
        _paginated(request, queryset, lambda item: change_request_data(item, internal=True))
    )


def _get_review_change(request, change_id):
    change = _review_queryset(request).filter(pk=change_id).first()
    if change is None:
        raise ScopedResourceNotFound("Packing change request is not available in the review scope.")
    return change


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_review_detail(request, change_id):
    return _success(change_request_data(_get_review_change(request, change_id), internal=True))


def _review_action(request, change_id, action):
    _get_review_change(request, change_id)
    serializer = PackingReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    if action == "reject_change" and not payload.get("review_note", "").strip():
        raise ValidationError({"review_note": "A rejection reason is required."})
    scope_key = f"packing:change-request:{change_id}"

    def callback(key):
        service = approve_packing_change if action == "approve_change" else reject_packing_change
        change, _, _ = service(
            change_request_id=change_id,
            reviewer=request.user,
            idempotency_key=key,
            **payload,
        )
        current = _change_queryset().get(pk=change.id)
        return change_request_data(current, internal=True), 200

    return execute_json_action(
        request,
        channel=INTERNAL,
        action=action,
        scope_key=scope_key,
        resource_key=scope_key,
        payload=payload,
        callback=callback,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_review_approve(request, change_id):
    return _review_action(request, change_id, "approve_change")


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_review_reject(request, change_id):
    return _review_action(request, change_id, "reject_change")


def _standard(request, *, internal):
    if internal:
        require_internal_permission(request.user, "supply.packing.view")
    else:
        supplier_id_for_user(request.user)
    standard = PackingStandardVersion.objects.filter(is_active=True).order_by(
        "code", "-version"
    ).first()
    if standard is None:
        raise ScopedResourceNotFound("The current packing standard is not available.")
    return _success(standard_data(standard))


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_standard(request):
    return _standard(request, internal=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_standard(request):
    return _standard(request, internal=False)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_standard(request):
    return _standard(request, internal=False)


def _label(request, *, channel, internal, batch_id=None, box_id=None):
    serializer = PackingLabelSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    if box_id is not None:
        queryset = _authorized_batches(
            request,
            "supply.packing.view",
            internal=internal,
        )
        batch = queryset.filter(boxes__id=box_id).first()
        if batch is None:
            key = idempotency_key(request)
            historical = (
                PackingApiIdempotencyRecord.objects.filter(
                    tenant=request.user.tenant,
                    idempotency_key=key,
                    action="generate_label",
                    scope_key=f"packing:box:{box_id}",
                    response_kind=PackingApiIdempotencyRecord.ResponseKind.LABEL,
                )
                .only("label_snapshot")
                .first()
            )
            batch_no = (
                historical.label_snapshot.get("batch_no")
                if historical and isinstance(historical.label_snapshot, dict)
                else None
            )
            if batch_no:
                batch = queryset.filter(batch_no=batch_no).first()
        if batch is None:
            raise ScopedResourceNotFound("Packing box is not available in the authorized scope.")
        batch_id = batch.id
        scope_key = f"packing:box:{box_id}"
    else:
        batch = _get_batch(
            request,
            batch_id,
            "supply.packing.view",
            internal=internal,
        )
        scope_key = f"packing:batch:{batch_id}"

    def callback(key, request_hash):
        return create_label_snapshot(
            batch_id=batch_id,
            box_id=box_id,
            actor=request.user,
            idempotency_key=key,
            request_hash=request_hash,
            expected_version=payload["expected_version"],
        )

    return execute_label_action(
        request,
        channel=channel,
        action="generate_label",
        scope_key=scope_key,
        resource_key=scope_key,
        payload=payload,
        callback=callback,
        renderer=render_label_pdf,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_batch_label(request, pk):
    return _label(request, channel=INTERNAL, internal=True, batch_id=pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_box_label(request, box_id):
    return _label(request, channel=INTERNAL, internal=True, box_id=box_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_batch_label(request, pk):
    return _label(request, channel=SUPPLIER_WEB, internal=False, batch_id=pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_box_label(request, box_id):
    return _label(request, channel=SUPPLIER_WEB, internal=False, box_id=box_id)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_batch_label(request, pk):
    return _label(request, channel=MINIAPP, internal=False, batch_id=pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_box_label(request, box_id):
    return _label(request, channel=MINIAPP, internal=False, box_id=box_id)
