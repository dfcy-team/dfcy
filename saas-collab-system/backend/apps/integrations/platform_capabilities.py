from dataclasses import dataclass

from rest_framework.exceptions import ValidationError


@dataclass(frozen=True)
class PlatformCapability:
    api_types: tuple[str, ...]
    authorization: str
    resources: dict[str, tuple[str, ...]]


CAPABILITY_REGISTRY = {
    "lazada": PlatformCapability(
        api_types=("marketplace",),
        authorization="oauth_store",
        resources={},
    ),
    "shopee": PlatformCapability(
        api_types=("marketplace", "advertising"),
        authorization="oauth_store",
        resources={"sales_order": ("live_readonly",), "refund_return": ("live_readonly",)},
    ),
    "tiktok": PlatformCapability(
        api_types=("marketplace", "advertising"),
        authorization="oauth_store",
        resources={"sales_order": ("live_readonly",), "refund_return": ("live_readonly",)},
    ),
    "jifeng_wms": PlatformCapability(
        api_types=("inventory",),
        authorization="warehouse_token",
        resources={"inventory_snapshot": ("live_readonly",)},
    ),
    "mock": PlatformCapability(
        api_types=("marketplace",),
        authorization="none",
        resources={"mock_record": ("mock",)},
    ),
}


def get_platform_capability(platform):
    key = str(platform or "").strip().lower()
    capability = CAPABILITY_REGISTRY.get(key)
    if capability is None:
        raise ValidationError("Unsupported platform capability.")
    return capability


def supports_resource(platform, resource_type, execution_mode):
    capability = CAPABILITY_REGISTRY.get(str(platform or "").strip().lower())
    if capability is None:
        return False
    return execution_mode in capability.resources.get(str(resource_type or ""), ())


def capability_payload(platform):
    capability = get_platform_capability(platform)
    return {
        "authorization": capability.authorization,
        "api_types": list(capability.api_types),
        "resources": {key: list(value) for key, value in capability.resources.items()},
    }
