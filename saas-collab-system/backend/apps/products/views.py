from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response
from apps.permissions.ui_p5_scopes import (
    filter_product_research,
    filter_product_skus,
    filter_product_spus,
    require_create_scope,
)

from .models import ProductResearch, ProductSKU, ProductSPU, ProductStatusRecommendation, ProductStatusTransition
from .permissions import (
    IsProductCodeFreezer,
    IsProductMasterReadOrManage,
    IsProductResearchReadOrManage,
    IsProductStatusConfirmer,
    IsProductStatusEvaluator,
    IsProductStatusViewer,
)
from .serializers import (
    ProductResearchSerializer,
    ProductSKUSerializer,
    ProductSPUSerializer,
    ProductStatusRecommendationSerializer,
    ProductStatusTransitionSerializer,
)
from .status_services import confirm_recommendation, evaluate_mock_status, reject_recommendation


def _serializer_context(request):
    return {"request": request}


@api_view(["GET", "POST"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_collection(request):
    if request.method == "GET":
        queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
        queryset = filter_product_research(request.user, queryset, "products.research.view")
        search = request.query_params.get("search", "").strip()
        platform = request.query_params.get("platform", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if platform:
            queryset = queryset.filter(platform=platform)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(request, queryset, ProductResearchSerializer, page=page, page_size=page_size)
        )

    require_create_scope(request.user, "products.research.manage", allow_own=True)
    serializer = ProductResearchSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ProductResearchSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_detail(request, pk):
    permission_code = "products.research.view" if request.method == "GET" else "products.research.manage"
    queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_research(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductResearchSerializer(item).data)

    serializer = ProductResearchSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductResearchSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_collection(request):
    if request.method == "GET":
        queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
        queryset = filter_product_spus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("sales_status", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if status:
            queryset = queryset.filter(sales_status=status)
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSPUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSPUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSPUSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_spus(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductSPUSerializer(item).data)

    serializer = ProductSPUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductSPUSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductCodeFreezer])
def freeze_product_spu_code(request, pk):
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_spus(request.user, queryset, "products.master.freeze"), pk=pk)
    item.is_code_frozen = True
    item.skus.update(is_code_frozen=True)
    item.save(update_fields=["is_code_frozen", "updated_at"])
    return success_response(ProductSPUSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_collection(request):
    if request.method == "GET":
        queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
        queryset = filter_product_skus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        spu_id = request.query_params.get("spu_id", "").strip()
        if search:
            queryset = queryset.filter(sku_code__icontains=search)
        if spu_id.isdigit():
            queryset = queryset.filter(spu_id=int(spu_id))
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSKUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSKUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSKUSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
    item = get_object_or_404(filter_product_skus(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductSKUSerializer(item).data)

    serializer = ProductSKUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductSKUSerializer(item).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_collection(request):
    queryset = ProductStatusRecommendation.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "source_snapshot",
        "confirmed_by",
    )
    return success_response(ProductStatusRecommendationSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_detail(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def confirm_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    transition = confirm_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    return success_response(ProductStatusTransitionSerializer(transition).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def reject_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    reject_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    recommendation.refresh_from_db()
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_transition_collection(request):
    queryset = ProductStatusTransition.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "recommendation",
        "approved_by",
    )
    return success_response(ProductStatusTransitionSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsProductStatusEvaluator])
def evaluate_mock_status_view(request):
    spu_id = request.data.get("spu")
    sku_id = request.data.get("sku")
    recommendation = evaluate_mock_status(
        tenant=request.user.tenant,
        user=request.user,
        spu_id=spu_id,
        sku_id=sku_id,
        metrics=request.data.get("metrics") or {},
    )
    return success_response(ProductStatusRecommendationSerializer(recommendation).data, status=201)
