from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsInternalUser

from .models import ProductResearch, ProductSKU, ProductSPU
from .serializers import ProductResearchSerializer, ProductSKUSerializer, ProductSPUSerializer


def _serializer_context(request):
    return {"request": request}


@api_view(["GET", "POST"])
@permission_classes([IsInternalUser])
def product_research_collection(request):
    if request.method == "GET":
        queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
        serializer = ProductResearchSerializer(queryset, many=True)
        return success_response(serializer.data)

    serializer = ProductResearchSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ProductResearchSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalUser])
def product_research_detail(request, pk):
    item = get_object_or_404(ProductResearch, pk=pk, tenant=request.user.tenant)
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
@permission_classes([IsInternalUser])
def product_spu_collection(request):
    if request.method == "GET":
        queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
        serializer = ProductSPUSerializer(queryset, many=True)
        return success_response(serializer.data)

    serializer = ProductSPUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSPUSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalUser])
def product_spu_detail(request, pk):
    item = get_object_or_404(ProductSPU, pk=pk, tenant=request.user.tenant)
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
@permission_classes([IsInternalUser])
def freeze_product_spu_code(request, pk):
    item = get_object_or_404(ProductSPU, pk=pk, tenant=request.user.tenant)
    item.is_code_frozen = True
    item.skus.update(is_code_frozen=True)
    item.save(update_fields=["is_code_frozen", "updated_at"])
    return success_response(ProductSPUSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsInternalUser])
def product_sku_collection(request):
    if request.method == "GET":
        queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
        serializer = ProductSKUSerializer(queryset, many=True)
        return success_response(serializer.data)

    serializer = ProductSKUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSKUSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalUser])
def product_sku_detail(request, pk):
    item = get_object_or_404(ProductSKU, pk=pk, tenant=request.user.tenant)
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
