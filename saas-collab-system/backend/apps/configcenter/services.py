from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.common.security import sanitize_sensitive_data
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from .models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion


SENSITIVE_REFERENCE_PREFIXES = ("placeholder://", "demo://", "not-configured")
_CHANGE_REASON_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(password|passwd|token|access[_-]?token|refresh[_-]?token|api[_-]?(key|secret)|"
    r"client[_-]?secret|app[_-]?secret|credential|secret)\s*[:=]"
)


def normalize_change_reason(reason, *, required=False, default=""):
    """Validate an operator-facing audit reason without accepting secrets."""
    if reason is None:
        reason = default
    if not isinstance(reason, str):
        raise ValidationError("Change reason must be a string.")
    reason = reason.strip()
    if not reason:
        if required:
            raise ValidationError("Change reason is required.")
        return ""
    if len(reason) < 5 or len(reason) > 240:
        raise ValidationError("Change reason must contain between 5 and 240 characters.")
    sanitized = sanitize_sensitive_data(reason)
    if sanitized != reason or _CHANGE_REASON_ASSIGNMENT_PATTERN.search(reason):
        raise ValidationError("Change reason must not contain credential or token assignments.")
    return reason


def _assert_permission(actor, code):
    if (
        not actor
        or not actor.is_active
        or actor.user_type != "internal"
        or not check_user_permission(actor, code)
        or not any(
            scope["scope_type"] == DataScope.ScopeType.ALL
            for scope in get_permission_data_scopes(actor, code)
        )
    ):
        raise PermissionDenied(f"{code} permission with all-tenant data scope is required.")


def _assert_scope_permission(actor, definition):
    if definition.scope_type != SystemConfigDefinition.ScopeType.SYSTEM:
        return
    system_permission = "config.system.manage"
    has_all_scope = any(
        scope["scope_type"] == DataScope.ScopeType.ALL
        for scope in get_permission_data_scopes(actor, system_permission)
    )
    if not check_user_permission(actor, system_permission) or not has_all_scope:
        raise PermissionDenied("System configuration permission with all-tenant data scope is required.")


def _normalize_value(definition, value):
    # The production runtime definition contains endpoint path keys such as
    # ``token_path``.  Those names are safe metadata, not credential values,
    # but the generic sanitizer intentionally rejects any key containing the
    # word ``token``.  Give this one definition its stricter domain validator
    # while preserving the generic guard for every other config key.
    if definition.config_key == "integrations.production.runtime" and not definition.is_sensitive:
        from apps.integrations.production_settings import validate_runtime_config

        return validate_runtime_config(value)
    if definition.is_sensitive:
        if not isinstance(value, dict) or set(value) - {"reference", "masked_metadata"}:
            raise ValidationError("Sensitive configs only accept placeholder reference metadata.")
        reference = str(value.get("reference") or "")
        if not reference.startswith(SENSITIVE_REFERENCE_PREFIXES):
            raise ValidationError("Sensitive config reference must be an explicit demo or placeholder reference.")
        sanitized = sanitize_sensitive_data(value)
        if sanitized != value:
            raise ValidationError("Credential-like sensitive config content is prohibited.")
        return value

    sanitized = sanitize_sensitive_data(value)
    if sanitized != value:
        raise ValidationError("Credential, token, cookie, session, and secret values are prohibited.")
    value_type = definition.value_type
    if value_type == SystemConfigDefinition.ValueType.STRING:
        if not isinstance(value, str):
            raise ValidationError("Config value must be a string.")
        return value
    if value_type == SystemConfigDefinition.ValueType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("Config value must be an integer.")
        return value
    if value_type == SystemConfigDefinition.ValueType.DECIMAL:
        try:
            return str(Decimal(str(value)))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Config value must be decimal-compatible.") from exc
    if value_type == SystemConfigDefinition.ValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError("Config value must be boolean.")
        return value
    if value_type == SystemConfigDefinition.ValueType.JSON:
        if not isinstance(value, (dict, list)):
            raise ValidationError("Config value must be a JSON object or array.")
        return value
    raise ValidationError("Unsupported config value type.")


def _scope(definition, actor):
    if definition.scope_type == SystemConfigDefinition.ScopeType.SYSTEM:
        return None, "system"
    return actor.tenant, f"tenant:{actor.tenant_id}"


def _write_log(*, version, actor, action, from_version, detail):
    log = ConfigChangeLog(
        tenant=version.tenant,
        config_key=version.config_key,
        scope_key=version.scope_key,
        from_version=from_version,
        to_version=version.version,
        actor=actor,
        action=action,
        masked_detail=detail,
    )
    log._config_service_write = True
    log.save()
    return log


def _supersede_effective(versions, *, except_id=None):
    for item in versions:
        if item.pk == except_id or item.status != TenantConfigVersion.Status.EFFECTIVE:
            continue
        item.status = TenantConfigVersion.Status.SUPERSEDED
        item._config_service_write = True
        item.save(update_fields=["status", "updated_at"])


def _latest_version(*, scope_key, config_key):
    """Return only the newest version while the definition lock is held.

    Configuration history is append-only and can grow for years. Loading and
    locking every historical row for each write made latency and lock duration
    grow with history size. The shared definition row is the serialization
    point for version allocation, so the newest row is sufficient here.
    """
    return TenantConfigVersion.objects.select_for_update().filter(
        scope_key=scope_key,
        config_key=config_key,
    ).order_by("-version", "-id").first()


def _effective_versions(*, scope_key, config_key):
    """Lock the small set of currently effective rows before superseding it."""
    return list(
        TenantConfigVersion.objects.select_for_update().filter(
            scope_key=scope_key,
            config_key=config_key,
            status=TenantConfigVersion.Status.EFFECTIVE,
        ).order_by("-version", "-id")
    )


def _create_version_locked(
    *, definition, actor, value, effective_at, action, source_version=None, change_reason=None, detail=None
):
    tenant, scope_key = _scope(definition, actor)
    latest = _latest_version(scope_key=scope_key, config_key=definition.config_key)
    next_version = latest.version + 1 if latest else 1
    status = (
        TenantConfigVersion.Status.PENDING_APPROVAL
        if definition.requires_approval
        else TenantConfigVersion.Status.EFFECTIVE
        if effective_at <= timezone.now()
        else TenantConfigVersion.Status.APPROVED
    )
    version = TenantConfigVersion(
        tenant=tenant,
        definition=definition,
        config_key=definition.config_key,
        scope_key=scope_key,
        version=next_version,
        value=_normalize_value(definition, value),
        status=status,
        effective_at=effective_at,
        created_by=actor,
    )
    version._config_service_write = True
    version.save()
    if status == TenantConfigVersion.Status.EFFECTIVE:
        _supersede_effective(
            _effective_versions(scope_key=scope_key, config_key=definition.config_key),
            except_id=version.id,
        )
    log_detail = {
        "scope": definition.scope_type,
        "status": status,
        "requires_approval": definition.requires_approval,
        "value_masked": definition.is_sensitive,
    }
    if detail:
        log_detail.update(detail)
    if change_reason:
        log_detail["change_reason"] = normalize_change_reason(change_reason, required=True)
    _write_log(
        version=version,
        actor=actor,
        action=action,
        from_version=source_version if source_version is not None else (latest.version if latest else None),
        detail=log_detail,
    )
    return version


@transaction.atomic
def create_config_version(*, definition, actor, value, effective_at, change_reason=None, detail=None):
    _assert_permission(actor, "config.manage")
    definition = SystemConfigDefinition.objects.select_for_update().get(pk=definition.pk)
    _assert_scope_permission(actor, definition)
    return _create_version_locked(
        definition=definition,
        actor=actor,
        value=value,
        effective_at=effective_at,
        action=ConfigChangeLog.Action.CREATE_VERSION,
        change_reason=change_reason,
        detail=detail,
    )


def _assert_version_scope(actor, version):
    if version.tenant_id is not None and version.tenant_id != actor.tenant_id:
        raise PermissionDenied("Config version is outside the current tenant.")
    _assert_scope_permission(actor, version.definition)


@transaction.atomic
def approve_config_version(*, version, actor, change_reason=None, detail=None):
    _assert_permission(actor, "config.approve")
    # Acquire the same per-definition serialization point used by creation and
    # rollback before reading the latest version. This prevents two concurrent
    # approvals from both treating different pending versions as current.
    definition = SystemConfigDefinition.objects.select_for_update().get(pk=version.definition_id)
    version = TenantConfigVersion.objects.select_for_update().select_related("created_by").get(pk=version.pk)
    version.definition = definition
    _assert_version_scope(actor, version)
    if version.status != TenantConfigVersion.Status.PENDING_APPROVAL:
        raise ValidationError("Only pending config versions can be approved.")
    if version.created_by_id == actor.id:
        raise ValidationError("Config creator cannot approve the same version.")
    latest = _latest_version(scope_key=version.scope_key, config_key=version.config_key)
    if latest is None or latest.pk != version.pk:
        raise ValidationError("Only the latest config version can be approved.")
    version.status = (
        TenantConfigVersion.Status.EFFECTIVE
        if version.effective_at <= timezone.now()
        else TenantConfigVersion.Status.APPROVED
    )
    version.approved_by = actor
    version._config_service_write = True
    version.save(update_fields=["status", "approved_by", "updated_at"])
    if version.status == TenantConfigVersion.Status.EFFECTIVE:
        _supersede_effective(
            _effective_versions(scope_key=version.scope_key, config_key=version.config_key),
            except_id=version.id,
        )
    log_detail = {"status": version.status, "value_masked": version.definition.is_sensitive}
    if detail:
        log_detail.update(detail)
    if change_reason:
        log_detail["change_reason"] = normalize_change_reason(change_reason, required=True)
    _write_log(
        version=version,
        actor=actor,
        action=ConfigChangeLog.Action.APPROVE,
        from_version=version.version,
        detail=log_detail,
    )
    return version


@transaction.atomic
def rollback_config_version(*, target_version, actor, effective_at=None, change_reason=None, detail=None):
    _assert_permission(actor, "config.rollback")
    definition = SystemConfigDefinition.objects.select_for_update().get(pk=target_version.definition_id)
    target_version = TenantConfigVersion.objects.select_for_update().get(pk=target_version.pk)
    target_version.definition = definition
    _assert_version_scope(actor, target_version)
    return _create_version_locked(
        definition=target_version.definition,
        actor=actor,
        value=target_version.value,
        effective_at=effective_at or timezone.now(),
        action=ConfigChangeLog.Action.ROLLBACK,
        source_version=target_version.version,
        change_reason=change_reason,
        detail=detail,
    )


def filter_visible_versions(user, queryset):
    tenant_queryset = queryset.filter(tenant=user.tenant)
    system_permission = "config.system.manage"
    can_manage_system = check_user_permission(user, system_permission) and any(
        scope["scope_type"] == DataScope.ScopeType.ALL
        for scope in get_permission_data_scopes(user, system_permission)
    )
    if can_manage_system:
        return queryset.filter(tenant=user.tenant) | queryset.filter(scope_key="system")
    return tenant_queryset
