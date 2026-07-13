from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import paginated_data, success_response
from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.permissions.services import check_user_permission

from .models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from .permissions import IsConfigApprover, IsConfigManager, IsConfigRollbackManager, IsConfigViewer
from .serializers import (
    ConfigChangeLogSerializer,
    ConfigQuerySerializer,
    ConfigRollbackSerializer,
    ConfigVersionCreateSerializer,
    SystemConfigDefinitionSerializer,
    TenantConfigVersionSerializer,
)
from .services import approve_config_version, create_config_version, filter_visible_versions, rollback_config_version


def _paginate(request, queryset, serializer_class, query):
    return paginated_data(request, queryset, serializer_class, page=query["page"], page_size=query["page_size"])


@api_view(["GET"])
@permission_classes([IsConfigViewer])
def definition_list(request):
    queryset = SystemConfigDefinition.objects.all()
    if not check_user_permission(request.user, "config.system.manage"):
        queryset = queryset.filter(scope_type=SystemConfigDefinition.ScopeType.TENANT)
    return success_response(SystemConfigDefinitionSerializer(queryset, many=True).data)


def _versions(request):
    queryset = TenantConfigVersion.objects.select_related("definition", "tenant", "created_by", "approved_by")
    return filter_visible_versions(request.user, queryset)


@api_view(["GET", "POST"])
def config_values(request):
    permission = IsConfigViewer() if request.method == "GET" else IsConfigManager()
    if not permission.has_permission(request, config_values):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Configuration permission is required.")
    if request.method == "POST":
        serializer = ConfigVersionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        definition = get_object_or_404(SystemConfigDefinition, config_key=serializer.validated_data["config_key"])
        try:
            version = create_config_version(
                definition=definition,
                actor=request.user,
                value=serializer.validated_data["value"],
                effective_at=serializer.validated_data["effective_at"],
            )
        except DjangoValidationError as exc:
            raise BusinessRuleViolation(str(exc)) from exc
        return success_response(TenantConfigVersionSerializer(version).data, status=201)
    query_serializer = ConfigQuerySerializer(data=request.query_params)
    query_serializer.is_valid(raise_exception=True)
    query = query_serializer.validated_data
    queryset = _versions(request)
    for field in ("config_key", "status"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_paginate(request, queryset, TenantConfigVersionSerializer, query))


@api_view(["POST"])
@permission_classes([IsConfigApprover])
def approve_value(request, pk):
    version = get_object_or_404(TenantConfigVersion.objects.select_related("definition"), pk=pk)
    try:
        version = approve_config_version(version=version, actor=request.user)
    except DjangoValidationError as exc:
        raise StateConflict(str(exc)) from exc
    return success_response(TenantConfigVersionSerializer(version).data)


@api_view(["POST"])
@permission_classes([IsConfigRollbackManager])
def rollback_value(request, pk):
    serializer = ConfigRollbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    version = get_object_or_404(TenantConfigVersion.objects.select_related("definition"), pk=pk)
    rolled_back = rollback_config_version(
        target_version=version,
        actor=request.user,
        effective_at=serializer.validated_data.get("effective_at"),
    )
    return success_response(TenantConfigVersionSerializer(rolled_back).data, status=201)


@api_view(["GET"])
@permission_classes([IsConfigViewer])
def change_log_list(request):
    serializer = ConfigQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = ConfigChangeLog.objects.filter(tenant=request.user.tenant)
    if check_user_permission(request.user, "config.system.manage"):
        queryset = ConfigChangeLog.objects.filter(tenant=request.user.tenant) | ConfigChangeLog.objects.filter(scope_key="system")
    if query.get("config_key"):
        queryset = queryset.filter(config_key=query["config_key"])
    return success_response(_paginate(request, queryset, ConfigChangeLogSerializer, query))
