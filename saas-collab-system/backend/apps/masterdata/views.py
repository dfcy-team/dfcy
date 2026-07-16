from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.exceptions import StateConflict
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import filter_master_data, require_all_scope
from apps.suppliers.models import SupplierTask

from .models import PlatformMaster, StatusChoices, SupplierMaster
from .serializers import MODEL_BY_RESOURCE, SERIALIZER_BY_RESOURCE


def positive_int(value, default, maximum=100):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Pagination values must be integers.")
    if parsed < 1 or parsed > maximum:
        raise ValidationError(f"Pagination value must be between 1 and {maximum}.")
    return parsed


def resource_contract(resource):
    if resource not in MODEL_BY_RESOURCE:
        raise NotFound("Unknown master-data resource.")
    return MODEL_BY_RESOURCE[resource], SERIALIZER_BY_RESOURCE[resource]


class MasterDataCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def get(self, request, resource):
        model, serializer = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        queryset = filter_master_data(request.user, queryset, self.read_permission_code, resource)
        if resource == "stores":
            queryset = queryset.select_related("platform")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        if status:
            queryset = queryset.filter(status=status)
        page = positive_int(request.query_params.get("page", 1), 1)
        page_size = positive_int(request.query_params.get("page_size", 20), 20)
        return success_response(paginated_data(request, queryset, serializer, page=page, page_size=page_size))

    def post(self, request, resource):
        require_all_scope(request.user, self.write_permission_code)
        _, serializer_class = resource_contract(resource)
        serializer = serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(tenant=request.user.tenant)
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="create",
            object_type=resource,
            object_id=instance.pk,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(serializer_class(instance, context={"request": request}).data, status=201)


class MasterDataDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def get_object(self, request, resource, pk):
        model, _ = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        permission_code = self.read_permission_code if request.method == "GET" else self.write_permission_code
        return get_object_or_404(filter_master_data(request.user, queryset, permission_code, resource), pk=pk)

    def get(self, request, resource, pk):
        instance = self.get_object(request, resource, pk)
        _, serializer_class = resource_contract(resource)
        return success_response(serializer_class(instance, context={"request": request}).data)

    def patch(self, request, resource, pk):
        instance = self.get_object(request, resource, pk)
        before = {"code": instance.code, "status": instance.status}
        _, serializer_class = resource_contract(resource)
        serializer = serializer_class(
            instance, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="update",
            object_type=resource,
            object_id=instance.pk,
            before_data=before,
            after_data={"code": instance.code, "status": instance.status},
        )
        return success_response(serializer.data)


class MasterDataStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.view"
    write_permission_code = "masterdata.manage"

    def post(self, request, resource, pk):
        model, serializer_class = resource_contract(resource)
        queryset = model.objects.filter(tenant=request.user.tenant)
        instance = get_object_or_404(
            filter_master_data(request.user, queryset, self.write_permission_code, resource),
            pk=pk,
        )
        status = request.data.get("status")
        if status not in StatusChoices.values:
            raise ValidationError({"status": "Status must be active or inactive."})
        if status == StatusChoices.INACTIVE and isinstance(instance, PlatformMaster) and instance.stores.filter(
            status=StatusChoices.ACTIVE
        ).exists():
            raise StateConflict("An active store still references this platform.")
        if status == StatusChoices.INACTIVE and isinstance(instance, SupplierMaster) and SupplierTask.objects.filter(
            tenant=request.user.tenant,
            supplier_id=instance.pk,
            status__in=["pending", "in_progress", "partial"],
        ).exists():
            raise StateConflict("An active supplier task still references this supplier.")
        before = instance.status
        instance.status = status
        instance.save(update_fields=["status", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="masterdata",
            action="status_change",
            object_type=resource,
            object_id=instance.pk,
            before_data={"status": before},
            after_data={"status": status},
        )
        return success_response(serializer_class(instance, context={"request": request}).data)
