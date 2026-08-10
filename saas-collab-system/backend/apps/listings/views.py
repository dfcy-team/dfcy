from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied

from apps.common.responses import success_response

from .models import ListingProfile, ListingTemplate
from .permissions import CanApproveListings, CanManageListings, CanManageTemplates, CanPublishListings, CanViewListings, CanViewTemplates
from .serializers import ListingProfileSerializer, ListingPublicationJobSerializer, ListingTemplateSerializer
from .services import approve_listing, queue_listing_publication, submit_listing_for_approval


def _require(request, permission):
    if not permission.has_permission(request, None):
        raise PermissionDenied()


@api_view(["GET", "POST"])
def template_collection(request):
    _require(request, CanViewTemplates() if request.method == "GET" else CanManageTemplates())
    if request.method == "GET":
        queryset = ListingTemplate.objects.filter(tenant=request.user.tenant).select_related("platform")
        return success_response(ListingTemplateSerializer(queryset, many=True).data)
    serializer = ListingTemplateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ListingTemplateSerializer(item).data, status=201)


@api_view(["GET", "POST"])
def profile_collection(request):
    _require(request, CanViewListings() if request.method == "GET" else CanManageListings())
    if request.method == "GET":
        queryset = ListingProfile.objects.filter(tenant=request.user.tenant).select_related("product", "store", "template").prefetch_related("variants")
        status = request.query_params.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        return success_response(ListingProfileSerializer(queryset, many=True).data)
    serializer = ListingProfileSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ListingProfileSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
def profile_detail(request, pk):
    _require(request, CanViewListings() if request.method == "GET" else CanManageListings())
    item = get_object_or_404(ListingProfile, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ListingProfileSerializer(item).data)
    if item.status not in {ListingProfile.Status.DRAFT, ListingProfile.Status.READY, ListingProfile.Status.FAILED}:
        from apps.common.exceptions import StateConflict
        raise StateConflict("Only an editable listing draft can be changed.")
    serializer = ListingProfileSerializer(item, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ListingProfileSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanManageListings])
def profile_submit(request, pk):
    return success_response(ListingProfileSerializer(submit_listing_for_approval(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanApproveListings])
def profile_approve(request, pk):
    return success_response(ListingProfileSerializer(approve_listing(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanPublishListings])
def profile_publish(request, pk):
    job, replayed = queue_listing_publication(profile_id=pk, actor=request.user, idempotency_key=request.headers.get("Idempotency-Key", ""), action=request.data.get("action", "create"))
    data = ListingPublicationJobSerializer(job).data
    data["replayed"] = replayed
    return success_response(data, status=200 if replayed else 201)
