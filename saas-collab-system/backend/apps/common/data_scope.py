from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes, get_user_data_scope


def custom_scope_allows(user, constraints, *, permission_code=None):
    """Return whether one user scope permits all configured target dimensions."""
    if getattr(user, "is_superuser", False):
        return True
    scopes = (
        get_permission_data_scopes(user, permission_code)
        if permission_code
        else get_user_data_scope(user)
    )
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return True

    normalized_constraints = {
        key: None if value is None else str(value)
        for key, value in constraints.items()
    }
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope.get("config") or {}
        configured = False
        permitted = True
        for key, target in normalized_constraints.items():
            allowed_values = config.get(key, [])
            if not allowed_values:
                continue
            configured = True
            permitted = permitted and target in {str(value) for value in allowed_values}
        if configured and permitted:
            return True
    return False


def custom_scope_allows_product(user, *, sku=None, spu=None, extra_constraints=None, permission_code=None):
    resolved_spu = spu or (sku.spu if sku else None)
    constraints = {
        "sku_ids": getattr(sku, "id", None),
        "spu_ids": getattr(resolved_spu, "id", None),
    }
    constraints.update(extra_constraints or {})
    return custom_scope_allows(user, constraints, permission_code=permission_code)
