from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import require_all_scope

from .models import Influencer
from .serializers import InfluencerSerializer


class InfluencerCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get(self, request):
        queryset = Influencer.objects.filter(tenant=request.user.tenant)
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search) | Q(handle__icontains=search))
        if status:
            queryset = queryset.filter(status=status)
        try:
            page, page_size = int(request.query_params.get("page", 1)), int(request.query_params.get("page_size", 20))
        except ValueError:
            raise ValidationError("Pagination values must be integers.")
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValidationError("Invalid pagination range.")
        return success_response(paginated_data(request, queryset, InfluencerSerializer, page=page, page_size=page_size))

    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        serializer = InfluencerSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant=request.user.tenant)
        write_operation_log(tenant=request.user.tenant, user=request.user, module="influencers", action="create",
                            object_type="influencer", object_id=instance.pk, after_data={"code": instance.code, "status": instance.status})
        return success_response(InfluencerSerializer(instance, context={"request": request}).data, status=201)


class InfluencerDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def get_object(self, request, pk):
        return get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)

    def get(self, request, pk):
        return success_response(InfluencerSerializer(self.get_object(request, pk), context={"request": request}).data)

    def patch(self, request, pk):
        instance = self.get_object(request, pk)
        before = {"code": instance.code, "status": instance.status}
        serializer = InfluencerSerializer(instance, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        write_operation_log(tenant=request.user.tenant, user=request.user, module="influencers", action="update",
                            object_type="influencer", object_id=instance.pk, before_data=before,
                            after_data={"code": instance.code, "status": instance.status})
        return success_response(serializer.data)


class InfluencerStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "influencers.view"
    write_permission_code = "influencers.manage"

    def post(self, request, pk):
        instance = get_object_or_404(Influencer, pk=pk, tenant=request.user.tenant)
        status = request.data.get("status")
        if status not in Influencer.Status.values:
            raise ValidationError({"status": "Status must be active or inactive."})
        before = instance.status
        instance.status = status
        instance.save(update_fields=["status", "updated_at"])
        write_operation_log(tenant=request.user.tenant, user=request.user, module="influencers", action="status_change",
                            object_type="influencer", object_id=instance.pk, before_data={"status": before}, after_data={"status": status})
        return success_response(InfluencerSerializer(instance, context={"request": request}).data)
