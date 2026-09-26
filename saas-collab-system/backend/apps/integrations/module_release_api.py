"""System-admin API for independent module-release configuration versions."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied

from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.responses import success_response
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from apps.configcenter.serializers import TenantConfigVersionSerializer
from apps.configcenter.services import approve_config_version, create_config_version, normalize_change_reason, rollback_config_version

from .module_release import MODULE_RELEASE_CONFIG_KEY, get_effective_module_release_version, get_module_release_config, validate_module_release_config
from .production_settings_api import (
    IsProductionSettingsApprover,
    IsProductionSettingsManager,
    IsProductionSettingsRollbackManager,
    IsProductionSettingsViewer,
    _has_all_scope,
)


class ModuleReleaseCreateSerializer(serializers.Serializer):
    value = serializers.JSONField(required=False)
    config = serializers.JSONField(required=False)
    effective_at = serializers.DateTimeField(required=False, default=timezone.now)
    change_reason = serializers.CharField(min_length=5, max_length=240, required=True, trim_whitespace=True)

    def validate(self, attrs):
        value = attrs.get("value", attrs.get("config"))
        if value is None:
            raise serializers.ValidationError({"value": "Module release configuration is required."})
        attrs["value"] = validate_module_release_config(value)
        return attrs


class ModuleReleaseActionSerializer(serializers.Serializer):
    effective_at = serializers.DateTimeField(required=False, default=timezone.now)
    change_reason = serializers.CharField(min_length=5, max_length=240, required=False, trim_whitespace=True)


def _definition():
    return SystemConfigDefinition.objects.get(config_key=MODULE_RELEASE_CONFIG_KEY)


def _version_data(version, change_reason=None):
    payload = TenantConfigVersionSerializer(version).data
    try:
        payload["value"] = validate_module_release_config(version.value)
    except DjangoValidationError:
        payload["value"] = "***"
        payload["value_masked"] = True
    if change_reason is None:
        change_reason = _change_reasons([version]).get(version.version, "")
    payload["change_reason"] = change_reason
    return payload


def _change_reasons(versions):
    if not versions:
        return {}
    reasons = {}
    logs = ConfigChangeLog.objects.filter(
        config_key=MODULE_RELEASE_CONFIG_KEY, scope_key="system",
        to_version__in=[item.version for item in versions],
        action__in=(ConfigChangeLog.Action.CREATE_VERSION, ConfigChangeLog.Action.ROLLBACK),
    ).order_by("-created_at", "-id").values_list("to_version", "masked_detail")
    for version_number, detail in logs:
        if version_number not in reasons and isinstance(detail, dict) and detail.get("change_reason"):
            reasons[version_number] = str(detail["change_reason"])
    return reasons


def _visible_versions():
    return list(TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by").filter(
        config_key=MODULE_RELEASE_CONFIG_KEY, scope_key="system",
        definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
    ).order_by("-version", "-id"))


def _payload(user):
    versions = _visible_versions()
    reasons = _change_reasons(versions)
    effective = next((item for item in versions if item.status == TenantConfigVersion.Status.EFFECTIVE), None)
    pending = next((item for item in versions if item.status == TenantConfigVersion.Status.PENDING_APPROVAL), None)
    legacy_or_effective = get_effective_module_release_version()
    return {
        "config_key": MODULE_RELEASE_CONFIG_KEY,
        "effective_config": {"modules": get_module_release_config()},
        "current_version": _version_data(effective, reasons.get(effective.version, "")) if effective else None,
        "pending_version": _version_data(pending, reasons.get(pending.version, "")) if pending else None,
        "versions": [_version_data(item, reasons.get(item.version, "")) for item in versions],
        "legacy_effective_version_id": legacy_or_effective.id if legacy_or_effective and legacy_or_effective.config_key != MODULE_RELEASE_CONFIG_KEY else None,
        "permissions": {
            "can_create": _has_all_scope(user, "config.manage"),
            "can_approve": _has_all_scope(user, "config.approve"),
            "can_rollback": _has_all_scope(user, "config.rollback"),
        },
    }


@api_view(["GET", "POST"])
def module_release_collection(request):
    if request.method == "GET":
        if not IsProductionSettingsViewer().has_permission(request, module_release_collection):
            raise PermissionDenied("System module release viewer permission is required.")
        return success_response(_payload(request.user))
    if not IsProductionSettingsManager().has_permission(request, module_release_collection):
        raise PermissionDenied("System module release manager permission is required.")
    serializer = ModuleReleaseCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        version = create_config_version(
            definition=_definition(), actor=request.user, value=serializer.validated_data["value"],
            effective_at=serializer.validated_data["effective_at"],
            change_reason=normalize_change_reason(serializer.validated_data["change_reason"], required=True),
        )
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return success_response({"version": _version_data(version), "module_release": _payload(request.user)}, status=201)


def _get_version(pk):
    return TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by").filter(
        pk=pk, config_key=MODULE_RELEASE_CONFIG_KEY, scope_key="system",
        definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
    ).first()


@api_view(["GET", "POST"])
def module_release_version(request, pk):
    version = _get_version(pk)
    if version is None:
        from django.http import Http404
        raise Http404
    if request.method == "GET":
        if not IsProductionSettingsViewer().has_permission(request, module_release_version):
            raise PermissionDenied("System module release viewer permission is required.")
        return success_response(_version_data(version))
    if not IsProductionSettingsApprover().has_permission(request, module_release_version):
        raise PermissionDenied("System module release approver permission is required.")
    serializer = ModuleReleaseActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        version = approve_config_version(
            version=version, actor=request.user,
            change_reason=normalize_change_reason(serializer.validated_data.get("change_reason"), default="审批模块发布控制版本"),
        )
    except DjangoValidationError as exc:
        raise StateConflict(str(exc)) from exc
    return success_response(_version_data(version), message="模块发布控制版本已审批生效。")


@api_view(["POST"])
def module_release_version_rollback(request, pk):
    version = _get_version(pk)
    if version is None:
        from django.http import Http404
        raise Http404
    if not IsProductionSettingsRollbackManager().has_permission(request, module_release_version_rollback):
        raise PermissionDenied("System module release rollback permission is required.")
    serializer = ModuleReleaseActionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        version = rollback_config_version(
            target_version=version, actor=request.user,
            effective_at=serializer.validated_data.get("effective_at"),
            change_reason=normalize_change_reason(serializer.validated_data.get("change_reason"), default="回滚模块发布控制版本"),
        )
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return success_response(_version_data(version), status=201)
