"""System-admin API for the versioned production runtime configuration."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
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

from .module_release import contains_module_release_data, is_legacy_module_release_config
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
        if contains_module_release_data(value):
            raise serializers.ValidationError({"value": "Module release data must use the module-release control endpoint."})
        attrs["value"] = validate_runtime_config(value)
        return attrs


class TikTokRenewalSelectionSerializer(serializers.Serializer):
    effective_version = serializers.IntegerField(min_value=1)
    latest_version = serializers.IntegerField(min_value=1)
    authorization_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=True, max_length=200
    )
    change_reason = serializers.CharField(min_length=5, max_length=240, trim_whitespace=True)

    def validate_authorization_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("店铺授权不能重复选择。")
        return value


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


def _preserve_omitted_tiktok_refresh_policy(value, effective_config):
    """Inherit omitted Shop lists while preserving explicit replacements, including []."""
    submitted_platforms = value.get("platforms") or {}
    submitted_tiktok = submitted_platforms.get("tiktok") or {}
    effective_tiktok = effective_config.get("platforms", {}).get("tiktok", {})
    inherited = {
        field: effective_tiktok[field]
        for field in ("auto_refresh_bindings", "auto_refresh_exclusions")
        if field not in submitted_tiktok and field in effective_tiktok
    }
    if not inherited:
        return value
    return {**value, "platforms": {**submitted_platforms, "tiktok": {**submitted_tiktok, **inherited}}}


def _version_data(version, change_reason=None):
    payload = TenantConfigVersionSerializer(version).data
    # The runtime validator rejects credentials, but do not expose a forged or
    # legacy invalid row if an operator imported old database data manually.
    try:
        payload["value"] = validate_runtime_config(version.value)
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
        config_key=CONFIG_KEY,
        scope_key="system",
        to_version__in=[item.version for item in versions],
        action__in=(ConfigChangeLog.Action.CREATE_VERSION, ConfigChangeLog.Action.ROLLBACK),
    ).order_by("-created_at", "-id").values_list("to_version", "masked_detail")
    for version_number, detail in logs:
        if version_number not in reasons and isinstance(detail, dict) and detail.get("change_reason"):
            reasons[version_number] = str(detail["change_reason"])
    return reasons


def _visible_versions():
    versions = (
        TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
        .filter(
            config_key=CONFIG_KEY,
            scope_key="system",
            definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
        )
        .order_by("-version", "-id")
    )
    # Keep accidental legacy module rows for audit/recovery, but do not expose
    # them as production-environment configuration history.
    return [item for item in versions if not is_legacy_module_release_config(item.value)]


def _runtime_payload(user):
    from .models import SyncSchedulerHeartbeat

    snapshot = runtime_snapshot()
    heartbeat = SyncSchedulerHeartbeat.objects.filter(key="credential-refresh").first()
    versions = _visible_versions()
    change_reasons = _change_reasons(versions)
    # During migration a modules-only legacy row may be the database row with
    # ``effective`` status while the runtime deliberately resolves the latest
    # complete (now superseded) document.  The read model must identify the
    # document actually governing production, not the legacy module row.
    effective = next((item for item in versions if item.id == snapshot.get("version_id")), None)
    if effective is None:
        effective = next((item for item in versions if item.status == TenantConfigVersion.Status.EFFECTIVE), None)
    pending = next((item for item in versions if item.status == TenantConfigVersion.Status.PENDING_APPROVAL), None)
    effective_data = _version_data(effective, change_reasons.get(effective.version, "")) if effective is not None else None
    pending_data = _version_data(pending, change_reasons.get(pending.version, "")) if pending is not None else None
    return {
        **snapshot,
        "auto_refresh_last_seen_at": heartbeat.last_seen_at.isoformat() if heartbeat else None,
        # Keep both explicit and compatibility names so the admin UI can
        # render the resolved document without knowing configcenter internals.
        "effective_config": snapshot["config"],
        "runtime": snapshot,
        "current_version": effective_data,
        "pending_version": pending_data,
        "effective": effective_data,
        "versions": [_version_data(item, change_reasons.get(item.version, "")) for item in versions],
        "permissions": {
            "can_create": _has_all_scope(user, "config.manage"),
            "can_approve": _has_all_scope(user, "config.approve"),
            "can_rollback": _has_all_scope(user, "config.rollback"),
        },
    }


def _renewal_rows(tenant_id):
    from .models import MarketplaceStoreAuthorization

    if tenant_id is None:
        return []
    return list(MarketplaceStoreAuthorization.objects.filter(
        tenant_id=tenant_id, platform="tiktok", status="active",
        store__tenant_id=tenant_id, integration_config__tenant_id=tenant_id,
        integration_config__platform="tiktok",
        integration_config__environment__in=("pilot", "production"),
        integration_config__status__in=("verified", "active"),
    ).exclude(token_id="").exclude(platform_store_id="").exclude(region="")
        .select_related("store").order_by("store__code", "region", "id"))


def _renewal_versions():
    return TenantConfigVersion.objects.filter(config_key=CONFIG_KEY, scope_key="system").order_by("-version")


def _renewal_bindings(value):
    return value.get("platforms", {}).get("tiktok", {}).get("auto_refresh_bindings") or []


def _tiktok_renewal_choices(user):
    from .tiktok_renewal_policy import binding_matches

    snapshot = runtime_snapshot()
    bindings = _renewal_bindings(snapshot["config"])
    tenant_id = user.tenant_id
    rows = _renewal_rows(tenant_id)
    versions = _renewal_versions()
    latest = versions.first()
    historical = []
    for value in versions.filter(
        approved_by__isnull=False,
        status__in=(TenantConfigVersion.Status.EFFECTIVE, TenantConfigVersion.Status.SUPERSEDED),
    ).values_list("value", flat=True)[:20]:
        historical.extend(_renewal_bindings(value))
    return {
        "effective_version": snapshot["effective_version"],
        "latest_version": latest.version if latest else None,
        "latest_pending": bool(latest and latest.status == TenantConfigVersion.Status.PENDING_APPROVAL),
        "shops": [
            {"id": row.pk, "store_code": row.store.code, "store_name": row.store.name, "region": row.region,
             "selected": binding_matches(row, bindings), "historical": binding_matches(row, historical)}
            for row in rows
        ],
        "unavailable_binding_count": sum(
            item.get("tenant_id") == tenant_id and not any(binding_matches(row, [item]) for row in rows)
            for item in bindings
        ),
    }


def _submit_tiktok_renewal_selection(request):
    from .tiktok_renewal_policy import binding_matches

    serializer = TikTokRenewalSelectionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    tenant_id = request.user.tenant_id
    if tenant_id is None:
        raise PermissionDenied("当前管理员没有可维护的租户。")
    try:
        with transaction.atomic():
            definition = SystemConfigDefinition.objects.select_for_update().get(config_key=CONFIG_KEY)
            snapshot = runtime_snapshot()
            versions = _renewal_versions()
            latest = versions.first()
            current = versions.filter(pk=snapshot["version_id"]).first()
            if (not current or current.version != values["effective_version"]
                    or not latest or latest.version != values["latest_version"]):
                raise StateConflict("配置版本已变化，请刷新店铺列表后重试。")
            if latest.status == TenantConfigVersion.Status.PENDING_APPROVAL:
                raise StateConflict("最新配置版本仍在等待审批，请处理后再提交。")
            rows = {row.pk: row for row in _renewal_rows(tenant_id)}
            selected = set(values["authorization_ids"])
            if selected - rows.keys():
                raise serializers.ValidationError({"authorization_ids": "所选店铺授权已失效或不属于当前租户。"})
            old = _renewal_bindings(snapshot["config"])
            if selected == {pk for pk, row in rows.items() if binding_matches(row, old)}:
                raise serializers.ValidationError({"authorization_ids": "店铺续期选择没有变化。"})
            preserved = [item for item in old if not any(binding_matches(row, [item]) for row in rows.values())]
            new = [
                {"tenant_id": row.tenant_id, "store_code": row.store.code, "region": row.region,
                 "platform_store_id": row.platform_store_id, "integration_config_id": row.integration_config_id}
                for pk, row in rows.items() if pk in selected
            ]
            config = validate_runtime_config(current.value)
            config.setdefault("platforms", {}).setdefault("tiktok", {})["auto_refresh_bindings"] = preserved + new
            version = create_config_version(
                definition=definition, actor=request.user, value=validate_runtime_config(config),
                effective_at=timezone.now(), change_reason=normalize_change_reason(values["change_reason"], required=True),
            )
    except DjangoValidationError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return success_response(
        {"version": {"id": version.pk, "version": version.version, "status": version.status}},
        message="店铺续期配置已提交审批。", status=201,
    )


@api_view(["GET", "POST"])
def production_settings_collection(request):
    if request.query_params.get("tiktok_renewal") == "1":
        if not IsProductionSettingsManager().has_permission(request, production_settings_collection):
            raise PermissionDenied("System production settings manager permission is required.")
        if request.method == "GET":
            return success_response(_tiktok_renewal_choices(request.user))
        return _submit_tiktok_renewal_selection(request)
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
        # Serialize effective-config lookup with every other config version
        # mutation. Approvals/activation use this same definition-row lock.
        with transaction.atomic():
            definition = SystemConfigDefinition.objects.select_for_update().get(config_key=CONFIG_KEY)
            current_config = runtime_snapshot()["config"]
            value = _preserve_omitted_tiktok_refresh_policy(serializer.validated_data["value"], current_config)
            version = create_config_version(
                definition=definition,
                actor=request.user,
                value=value,
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
    if contains_module_release_data(version.value):
        raise StateConflict("Legacy production configuration containing module release data cannot be approved. Create separate production and module-release versions instead.")
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
    if contains_module_release_data(version.value):
        raise StateConflict("Legacy production configuration containing module release data cannot be rolled back. Create separate production and module-release versions instead.")
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
