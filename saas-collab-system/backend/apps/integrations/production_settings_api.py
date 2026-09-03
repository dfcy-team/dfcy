"""System-admin API for the versioned production runtime configuration."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.responses import success_response
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from apps.configcenter.serializers import TenantConfigVersionSerializer
from apps.configcenter.services import (
    approve_config_version,
    create_config_version,
    normalize_change_reason,
    rollback_config_version,
)
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from .production_settings import CONFIG_KEY, runtime_snapshot, validate_runtime_config


def _has_all_scope(user, permission_code):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and getattr(user, "user_type", None) == "internal"
        and check_user_permission(user, permission_code)
        and any(
            scope["scope_type"] == DataScope.ScopeType.ALL
            for scope in get_permission_data_scopes(user, permission_code)
        )
    )


class ProductionSettingsPermission(BasePermission):
    """Require the system permission and the action's ALL data scope."""

    action_permission = None

    def has_permission(self, request, view):
        return _has_all_scope(request.user, "config.system.manage") and _has_all_scope(
            request.user, self.action_permission
        )


class IsProductionSettingsViewer(ProductionSettingsPermission):
    action_permission = "config.view"


class IsProductionSettingsManager(ProductionSettingsPermission):
    action_permission = "config.manage"


class IsProductionSettingsApprover(ProductionSettingsPermission):
    action_permission = "config.approve"


class IsProductionSettingsRollbackManager(ProductionSettingsPermission):
    action_permission = "config.rollback"


class ProductionRuntimeVersionCreateSerializer(serializers.Serializer):
    value = serializers.JSONField(required=False)
    config = serializers.JSONField(required=False)
    effective_at = serializers.DateTimeField(required=False, default=timezone.now)
    change_reason = serializers.CharField(min_length=5, max_length=240, required=True, trim_whitespace=True)

    def validate(self, attrs):
        value = attrs.get("value", attrs.get("config"))
        if value is None:
            raise serializers.ValidationError({"value": "Runtime configuration is required."})
        attrs["value"] = validate_runtime_config(value)
        return attrs


class ProductionRuntimeRollbackSerializer(serializers.Serializer):
    effective_at = serializers.DateTimeField(required=False, default=timezone.now)
    change_reason = serializers.CharField(
        min_length=5,
        max_length=240,
        required=False,
        default="回滚生产运行时配置版本",
        trim_whitespace=True,
    )


class ProductionRuntimeApprovalSerializer(serializers.Serializer):
    change_reason = serializers.CharField(
        min_length=5,
        max_length=240,
        required=False,
        default="审批生产运行时配置版本",
        trim_whitespace=True,
    )


def _definition():
    return SystemConfigDefinition.objects.get(config_key=CONFIG_KEY)


def _version_data(version):
    payload = TenantConfigVersionSerializer(version).data
    # The runtime validator rejects credentials, but do not expose a forged or
    # legacy invalid row if an operator imported old database data manually.
    try:
        payload["value"] = validate_runtime_config(version.value)
    except DjangoValidationError:
        payload["value"] = "***"
        payload["value_masked"] = True
    payload["change_reason"] = ""
    for log in ConfigChangeLog.objects.filter(
        config_key=version.config_key,
        scope_key=version.scope_key,
        to_version=version.version,
        action__in=(ConfigChangeLog.Action.CREATE_VERSION, ConfigChangeLog.Action.ROLLBACK),
    ).order_by("-created_at", "-id"):
        detail = log.masked_detail if isinstance(log.masked_detail, dict) else {}
        if detail.get("change_reason"):
            payload["change_reason"] = str(detail["change_reason"])
            break
    return payload


def _visible_versions():
    return list(
        TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
        .filter(
            config_key=CONFIG_KEY,
            scope_key="system",
            definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
        )
        .order_by("-version", "-id")
    )


def _runtime_payload(user):
    snapshot = runtime_snapshot()
    versions = _visible_versions()
    effective = next((item for item in versions if item.status == TenantConfigVersion.Status.EFFECTIVE), None)
    pending = next((item for item in versions if item.status == TenantConfigVersion.Status.PENDING_APPROVAL), None)
    effective_data = _version_data(effective) if effective is not None else None
    pending_data = _version_data(pending) if pending is not None else None
    return {
        **snapshot,
        # Keep both explicit and compatibility names so the admin UI can
        # render the resolved document without knowing configcenter internals.
        "effective_config": snapshot["config"],
        "runtime": snapshot,
        "current_version": effective_data,
        "pending_version": pending_data,
        "effective": effective_data,
        "versions": [_version_data(item) for item in versions],
        "permissions": {
            "can_create": _has_all_scope(user, "config.manage"),
            "can_approve": _has_all_scope(user, "config.approve"),
            "can_rollback": _has_all_scope(user, "config.rollback"),
        },
    }


@api_view(["GET", "POST"])
def production_settings_collection(request):
    if request.method == "GET":
        if not IsProductionSettingsViewer().has_permission(request, production_settings_collection):
            raise PermissionDenied("System production settings viewer permission is required.")
        return success_response(_runtime_payload(request.user))

    if not IsProductionSettingsManager().has_permission(request, production_settings_collection):
        raise PermissionDenied("System production settings manager permission is required.")
    serializer = ProductionRuntimeVersionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    change_reason = normalize_change_reason(serializer.validated_data["change_reason"], required=True)
    try:
        version = create_config_version(
            definition=_definition(),
            actor=request.user,
            value=serializer.validated_data["value"],
            effective_at=serializer.validated_data["effective_at"],
            change_reason=change_reason,
        )
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return success_response(
        {"version": _version_data(version), "runtime": _runtime_payload(request.user)},
        message="生产运行时配置版本已创建，等待系统管理员审批。",
        status=201,
    )


def _get_version(pk):
    return (
        TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
        .filter(
            pk=pk,
            config_key=CONFIG_KEY,
            scope_key="system",
            definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
        )
        .first()
    )


@api_view(["GET", "POST"])
def production_settings_version(request, pk):
    version = _get_version(pk)
    if version is None:
        from django.http import Http404

        raise Http404

    if request.method == "GET":
        if not IsProductionSettingsViewer().has_permission(request, production_settings_version):
            raise PermissionDenied("System production settings viewer permission is required.")
        return success_response(_version_data(version))

    if not IsProductionSettingsApprover().has_permission(request, production_settings_version):
        raise PermissionDenied("System production settings approver permission is required.")
    serializer = ProductionRuntimeApprovalSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        updated = approve_config_version(
            version=version,
            actor=request.user,
            change_reason=normalize_change_reason(serializer.validated_data["change_reason"], required=True),
        )
    except DjangoValidationError as exc:
        raise StateConflict(str(exc)) from exc
    return success_response(_version_data(updated), message="生产运行时配置版本已审批生效。")


@api_view(["POST"])
def production_settings_version_rollback(request, pk):
    version = _get_version(pk)
    if version is None:
        from django.http import Http404

        raise Http404
    if not IsProductionSettingsRollbackManager().has_permission(request, production_settings_version_rollback):
        raise PermissionDenied("System production settings rollback permission is required.")
    serializer = ProductionRuntimeRollbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        rolled_back = rollback_config_version(
            target_version=version,
            actor=request.user,
            effective_at=serializer.validated_data.get("effective_at"),
            change_reason=normalize_change_reason(serializer.validated_data["change_reason"], required=True),
        )
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return success_response(_version_data(rolled_back), message="生产运行时配置已创建回滚版本。", status=201)
