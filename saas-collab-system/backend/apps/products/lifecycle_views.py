from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound

from apps.common.responses import success_response

from .lifecycle_services import decide_lifecycle_review, evaluate_lifecycle_review
from .models import ProductLifecycleDecision, ProductLifecycleReview, ProductSKU, ProductSPU
from .permissions import IsLifecycleConfirmer, IsLifecycleEvaluator, IsLifecycleViewer, filter_lifecycle_reviews
from .serializers import (
    ProductLifecycleDecisionRequestSerializer,
    ProductLifecycleDecisionSerializer,
    ProductLifecycleEvaluationSerializer,
    ProductLifecycleQuerySerializer,
    ProductLifecycleReviewSerializer,
)


def _reviews(request):
    return filter_lifecycle_reviews(
        request.user,
        ProductLifecycleReview.objects.select_related("spu", "sku", "reviewed_by"),
    )


def _paginate(queryset, serializer_class, query):
    paginator = Paginator(queryset, query["page_size"])
    if query["page"] > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page = paginator.page(query["page"])
    return {
        "items": serializer_class(page.object_list, many=True).data,
        "pagination": {
            "page": page.number,
            "page_size": query["page_size"],
            "total": paginator.count,
            "total_pages": paginator.num_pages,
        },
    }


@api_view(["GET"])
@permission_classes([IsLifecycleViewer])
def review_list(request):
    serializer = ProductLifecycleQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = _reviews(request)
    for field in ("status", "recommended_stage"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_paginate(queryset, ProductLifecycleReviewSerializer, query))


@api_view(["GET"])
@permission_classes([IsLifecycleViewer])
def review_detail(request, pk):
    return success_response(ProductLifecycleReviewSerializer(get_object_or_404(_reviews(request), pk=pk)).data)


@api_view(["POST"])
@permission_classes([IsLifecycleEvaluator])
def evaluate_mock(request):
    serializer = ProductLifecycleEvaluationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    spu_id = values.pop("spu_id", None)
    sku_id = values.pop("sku_id", None)
    spu = get_object_or_404(ProductSPU, pk=spu_id, tenant=request.user.tenant) if spu_id else None
    sku = get_object_or_404(ProductSKU, pk=sku_id, tenant=request.user.tenant) if sku_id else None
    review = evaluate_lifecycle_review(
        tenant=request.user.tenant,
        spu=spu,
        sku=sku,
        source_type="mock",
        **values,
    )
    return success_response({"review": ProductLifecycleReviewSerializer(review).data, "mode": "mock"}, status=201)


def _decide(request, pk, decision):
    serializer = ProductLifecycleDecisionRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    review = get_object_or_404(_reviews(request), pk=pk)
    record = decide_lifecycle_review(
        review=review,
        actor=request.user,
        decision=decision,
        reason=serializer.validated_data["reason"],
    )
    return success_response(ProductLifecycleDecisionSerializer(record).data)


@api_view(["POST"])
@permission_classes([IsLifecycleConfirmer])
def confirm_review(request, pk):
    return _decide(request, pk, ProductLifecycleDecision.Decision.CONFIRM)


@api_view(["POST"])
@permission_classes([IsLifecycleConfirmer])
def reject_review(request, pk):
    return _decide(request, pk, ProductLifecycleDecision.Decision.REJECT)


@api_view(["GET"])
@permission_classes([IsLifecycleViewer])
def decision_list(request):
    serializer = ProductLifecycleQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    allowed_reviews = _reviews(request).values("id")
    queryset = ProductLifecycleDecision.objects.filter(
        tenant=request.user.tenant,
        review_id__in=allowed_reviews,
    ).select_related("review", "actor")
    return success_response(_paginate(queryset, ProductLifecycleDecisionSerializer, query))
