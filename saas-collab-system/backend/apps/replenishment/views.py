from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied

from apps.common.data_scope import custom_scope_allows_product
from apps.common.exceptions import StateConflict
from apps.common.responses import paginated_data, success_response
from apps.products.models import ProductSKU, ProductSPU

from .models import ReplenishmentRecommendation
from .permissions import IsReplenishmentEvaluator, IsReplenishmentReviewer, IsReplenishmentViewer, filter_recommendations
from .serializers import (
    ReplenishmentEvaluationSerializer,
    ReplenishmentQuerySerializer,
    ReplenishmentRecommendationSerializer,
    ReplenishmentReviewSerializer,
)
from .services import evaluate_replenishment, review_recommendation


def _queryset(request, permission_code="replenishment.view"):
    return filter_recommendations(
        request.user,
        ReplenishmentRecommendation.objects.select_related("spu", "sku", "reviewed_by"),
        permission_code,
    )


@api_view(["GET"])
@permission_classes([IsReplenishmentViewer])
def recommendation_list(request):
    serializer = ReplenishmentQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = _queryset(request)
    if query.get("status"):
        queryset = queryset.filter(status=query["status"])
    return success_response(
        paginated_data(
            request,
            queryset,
            ReplenishmentRecommendationSerializer,
            page=query["page"],
            page_size=query["page_size"],
        )
    )


@api_view(["GET"])
@permission_classes([IsReplenishmentViewer])
def recommendation_detail(request, pk):
    return success_response(ReplenishmentRecommendationSerializer(get_object_or_404(_queryset(request), pk=pk)).data)


@api_view(["POST"])
@permission_classes([IsReplenishmentEvaluator])
def evaluate_mock(request):
    serializer = ReplenishmentEvaluationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    sku_id = values.pop("sku_id", None)
    spu_id = values.pop("spu_id", None)
    sku = get_object_or_404(ProductSKU, pk=sku_id, tenant=request.user.tenant) if sku_id else None
    spu = get_object_or_404(ProductSPU, pk=spu_id, tenant=request.user.tenant) if spu_id else None
    if not custom_scope_allows_product(
        request.user,
        sku=sku,
        spu=spu,
        permission_code="replenishment.evaluate",
    ):
        raise PermissionDenied("Replenishment target is outside the authorized data scope.")
    recommendation = evaluate_replenishment(tenant=request.user.tenant, sku=sku, spu=spu, **values)
    return success_response({"recommendation": ReplenishmentRecommendationSerializer(recommendation).data, "mode": "mock"}, status=201)


def _review(request, pk, decision):
    serializer = ReplenishmentReviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    recommendation = get_object_or_404(_queryset(request, "replenishment.review"), pk=pk)
    try:
        recommendation = review_recommendation(
            recommendation=recommendation,
            actor=request.user,
            decision=decision,
            reason=serializer.validated_data["reason"],
        )
    except DjangoValidationError as exc:
        raise StateConflict(str(exc)) from exc
    return success_response(ReplenishmentRecommendationSerializer(recommendation).data)


@api_view(["POST"])
@permission_classes([IsReplenishmentReviewer])
def accept_recommendation(request, pk):
    return _review(request, pk, ReplenishmentRecommendation.Status.ACCEPTED)


@api_view(["POST"])
@permission_classes([IsReplenishmentReviewer])
def reject_recommendation(request, pk):
    return _review(request, pk, ReplenishmentRecommendation.Status.REJECTED)
