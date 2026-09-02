import re
import traceback as traceback_module

from django.db.models import Q

from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes

from .models import OperationLog, SystemExceptionLog


# Operation logs are intentionally useful for governance without becoming a
# second credential store.  Keep this list conservative: keys that identify a
# secret, session, bearer credential, or encrypted credential are always
# replaced before a value leaves the audit boundary.
_SENSITIVE_KEY_NAMES = {
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "cookie",
    "session",
    "sessionid",
    "apikey",
    "apisecret",
    "privatekey",
    "connectionstring",
    "proxyurl",
    "authorization",
    "bearer",
    "clientsecret",
    "credentialciphertext",
    "encryptedcredential",
    "rawcredential",
    "credentialvalue",
    "credential",
    "credentials",
    "secretkey",
    "signingkey",
    "encryptionkey",
}
# These are opaque business-record identifiers, not credential material.
# Keep the allow-list exact so similarly named headers or values remain
# redacted by the conservative marker checks below.
_SAFE_METADATA_KEY_NAMES = {"authorizationid"}
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
    ),
    re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|redis|rediss|mongodb(?:\+srv)?)://[^\s]+"
    ),
    re.compile(
        r"(?i)\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
    re.compile(
        r"(?i)(\b(?:api[_-]?key|api[_-]?secret|access[_-]?token|refresh[_-]?token|password|secret|token|credential|authorization|private[_-]?key|signing[_-]?key|encryption[_-]?key)\s*[:=]\s*)[^,;\s}]+"
    ),
)

MAX_SNAPSHOT_DEPTH = 8
MAX_SNAPSHOT_ITEMS = 200
MAX_SNAPSHOT_TEXT = 4096
MAX_SCOPE_VALUES = 500
MAX_USER_AGENT_LENGTH = 2048

# The role editor stores generic ID dimensions.  For audit records these
# dimensions refer to the audited object rather than to the operator.  Keep
# the aliases broad enough to cover the object_type values emitted by the
# existing modules while remaining an exact allow-list.
_OBJECT_SCOPE_TYPES = {
    "role_ids": ("role",),
    "platform_ids": ("platform", "platforms"),
    "store_ids": ("store", "stores"),
    "site_ids": ("site", "sites"),
    "warehouse_ids": ("warehouse", "warehouses"),
    "supplier_ids": ("supplier", "suppliers"),
}


def _normalized_key(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key):
    normalized = _normalized_key(key)
    if normalized in _SAFE_METADATA_KEY_NAMES:
        return False
    return normalized in _SENSITIVE_KEY_NAMES or any(
        marker in normalized
        for marker in (
            "password",
            "passwd",
            "passphrase",
            "secret",
            "token",
            "apikey",
            "privatekey",
            "sessionid",
            "cookie",
            "authorization",
            "connectionstring",
            "proxyurl",
            "credentialciphertext",
            "encryptedcredential",
            "rawcredential",
            "credential",
            "signingkey",
            "encryptionkey",
        )
    )


def redact_audit_value(value, *, key=None, depth=0):
    """Return a bounded, JSON-compatible value safe for audit consumers.

    ``before_data`` and ``after_data`` are written by many independent
    modules.  Redaction therefore happens at read time as a defense in depth
    layer even if an upstream caller accidentally persisted a sensitive key.
    """
    if key is not None and is_sensitive_key(key):
        return "[REDACTED]"
    if depth > MAX_SNAPSHOT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_audit_value(item_value, key=item_key, depth=depth + 1)
            for item_key, item_value in list(value.items())[:MAX_SNAPSHOT_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [
            redact_audit_value(item, depth=depth + 1)
            for item in list(value)[:MAX_SNAPSHOT_ITEMS]
        ]
    if isinstance(value, str):
        redacted = value
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            redacted = pattern.sub(
                lambda match: (
                    f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]"
                ),
                redacted,
            )
        return redacted[:MAX_SNAPSHOT_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_SNAPSHOT_TEXT]


def _scope_values(scope, *keys, numeric=False):
    """Return ``(values, configured, valid)`` for one scope dimension.

    DataScope is JSON and may contain stale or manually-corrupted values even
    when the role editor validates new writes.  Invalid dimensions must never
    be ignored: doing so could turn another configured dimension into a wider
    grant.  Empty arrays are treated as an unselected optional dimension so
    the role editor can send its standard shape.
    """
    config = scope.get("config") or {}
    for key in keys:
        if key not in config:
            continue
        values = config.get(key)
        if not isinstance(values, (list, tuple, set)):
            return [], True, False
        if len(values) > MAX_SCOPE_VALUES:
            return [], True, False
        if not values:
            continue
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        if not cleaned:
            continue
        if numeric:
            # Keep the scope fail-closed if an otherwise valid ID list was
            # corrupted with a non-positive/non-numeric value.
            if any(not value.isdigit() or int(value) < 1 for value in cleaned):
                return [], True, False
        return cleaned, True, True
    return [], False, True


def _scope_clause(scope, user):
    """Build the OperationLog predicate for one permission-specific scope.

    Scope dimensions inside one custom scope are ANDed; multiple scope rows
    are ORed by ``operation_log_queryset``.  Unsupported/empty custom config
    grants no rows, preserving fail-closed behavior for malformed scopes.
    """
    scope_type = scope.get("scope_type")
    if scope_type == DataScope.ScopeType.ALL:
        return Q(), True
    if scope_type == DataScope.ScopeType.OWN:
        if not getattr(user, "pk", None):
            return Q(pk__in=[]), False
        return Q(user_id=user.pk), True
    if scope_type == DataScope.ScopeType.DEPARTMENT:
        department_id = getattr(getattr(user, "internal_profile", None), "department_id", None)
        if not department_id:
            return Q(pk__in=[]), False
        return Q(user__internal_profile__department_id=department_id), True
    if scope_type != DataScope.ScopeType.CUSTOM:
        return Q(pk__in=[]), False

    clause = Q()
    configured = False
    user_ids, user_configured, user_valid = _scope_values(
        scope, "user_ids", "operator_ids", "actor_ids", numeric=True
    )
    if user_configured and not user_valid:
        return Q(pk__in=[]), False
    if user_ids:
        clause &= Q(user_id__in=user_ids)
        configured = True
    department_ids, department_configured, department_valid = _scope_values(
        scope, "department_ids", numeric=True
    )
    if department_configured and not department_valid:
        return Q(pk__in=[]), False
    if department_ids:
        clause &= Q(user__internal_profile__department_id__in=department_ids)
        configured = True
    modules, modules_configured, modules_valid = _scope_values(scope, "modules", "module_codes")
    if modules_configured and not modules_valid:
        return Q(pk__in=[]), False
    if modules:
        clause &= Q(module__in=modules)
        configured = True
    actions, actions_configured, actions_valid = _scope_values(scope, "actions", "action_codes")
    if actions_configured and not actions_valid:
        return Q(pk__in=[]), False
    if actions:
        clause &= Q(action__in=actions)
        configured = True
    object_types, object_types_configured, object_types_valid = _scope_values(scope, "object_types")
    if object_types_configured and not object_types_valid:
        return Q(pk__in=[]), False
    if object_types:
        clause &= Q(object_type__in=object_types)
        configured = True
    object_ids, object_ids_configured, object_ids_valid = _scope_values(scope, "object_ids")
    if object_ids_configured and not object_ids_valid:
        return Q(pk__in=[]), False
    if object_ids:
        clause &= Q(object_id__in=object_ids)
        configured = True

    for config_key, object_types_for_key in _OBJECT_SCOPE_TYPES.items():
        scoped_ids, scoped_configured, scoped_valid = _scope_values(
            scope, config_key, numeric=True
        )
        if scoped_configured and not scoped_valid:
            return Q(pk__in=[]), False
        if scoped_ids:
            clause &= Q(object_type__in=object_types_for_key, object_id__in=scoped_ids)
            configured = True
    return clause, configured


def operation_log_queryset(user, permission_code="audit.operation_logs.view"):
    """Return only logs visible to ``user`` under the exact permission scope."""
    tenant_id = getattr(user, "tenant_id", None)
    if tenant_id is None:
        return OperationLog.objects.none()
    queryset = OperationLog.objects.filter(tenant_id=tenant_id).filter(
        Q(user__isnull=True) | Q(user__tenant_id=tenant_id)
    ).select_related(
        "tenant", "user", "user__internal_profile"
    )
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope.get("scope_type") == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        clause, configured = _scope_clause(scope, user)
        if configured:
            allowed |= clause
    return queryset.filter(allowed).distinct()


def operation_log_payload(log, *, include_changes=False):
    operator = log.user
    payload = {
        "id": log.pk,
        "tenant_id": log.tenant_id,
        "operator": operator.username if operator else "system",
        "operator_id": operator.pk if operator else None,
        "operator_name": (operator.full_name or operator.username) if operator else "system",
        "module": log.module,
        "action": log.action,
        "object_type": log.object_type,
        "object_id": log.object_id,
        "ip_address": log.ip_address,
        "created_at": log.created_at,
    }
    if include_changes:
        payload["before_data"] = redact_audit_value(log.before_data or {})
        payload["after_data"] = redact_audit_value(log.after_data or {})
    return payload


def write_operation_log(
    *,
    tenant,
    user=None,
    module,
    action,
    object_type="",
    object_id="",
    before_data=None,
    after_data=None,
    ip_address=None,
    user_agent="",
):
    return OperationLog.objects.create(
        tenant=tenant,
        user=user,
        module=str(module or "")[:80],
        action=str(action or "")[:80],
        object_type=str(object_type or "")[:100],
        object_id=str(object_id)[:100] if object_id is not None else "",
        # Redact and bound snapshots at write time to avoid persisting secrets
        # or accepting an unbounded JSON payload.  Read-time redaction remains
        # in place as defense in depth for historical rows.
        before_data=redact_audit_value(before_data or {}),
        after_data=redact_audit_value(after_data or {}),
        ip_address=ip_address,
        user_agent=str(user_agent or "")[:MAX_USER_AGENT_LENGTH],
    )


def write_exception_log(*, module, exception, tenant=None, context=None, severity=SystemExceptionLog.Severity.ERROR):
    return SystemExceptionLog.objects.create(
        tenant=tenant,
        module=module,
        exception_type=exception.__class__.__name__,
        message=str(exception),
        traceback="".join(traceback_module.format_exception(type(exception), exception, exception.__traceback__)),
        context=context or {},
        severity=severity,
    )
