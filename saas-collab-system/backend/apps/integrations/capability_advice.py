from .capability_gate import RESOURCE_CAPABILITY
from .models import ConnectionCapability, MarketplaceStoreAuthorization
from .platform_capabilities import CAPABILITY_REGISTRY


DEFAULT_SYNC_MODE = ConnectionCapability.SyncMode.SCHEDULED


def capability_suggestions(authorization):
    """Return read-only proposals derived from the executable platform registry.

    Suggestions are deliberately not persisted. The existing capability PUT is
    the human approval boundary.
    """
    platform = CAPABILITY_REGISTRY.get(str(authorization.platform or "").strip().lower())
    if platform is None:
        return []

    suggestions = []
    seen = set()
    for resource_type, execution_modes in platform.resources.items():
        capability_code = RESOURCE_CAPABILITY.get(resource_type)
        if capability_code is None or "live_readonly" not in execution_modes or capability_code in seen:
            continue
        seen.add(capability_code)
        can_activate = authorization.status == MarketplaceStoreAuthorization.Status.ACTIVE
        suggestions.append({
            "capability_code": capability_code,
            "read_enabled": True,
            "write_enabled": False,
            "sync_mode": DEFAULT_SYNC_MODE,
            "source_priority": 100,
            "status": ConnectionCapability.Status.ACTIVE if can_activate else ConnectionCapability.Status.CONFIGURED,
            "confidence": "medium",
            "scope_verification": "unverified",
            "evidence": {
                "platform": authorization.platform,
                "resource_type": resource_type,
                "execution_mode": "live_readonly",
                "authorization_status": authorization.status,
            },
            "reason": "Platform registry supports read-only synchronization; confirm granted scopes before applying.",
        })
    return suggestions
