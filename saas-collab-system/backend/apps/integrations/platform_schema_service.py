"""Versioned, non-secret platform configuration schemas for the admin UI."""

from django.core.exceptions import ValidationError

from .platform_capabilities import CAPABILITY_REGISTRY, capability_payload, get_platform_capability


REGIONS = [
    {"value": "PH", "label": "Philippines (PH)"},
    {"value": "TH", "label": "Thailand (TH)"},
    {"value": "MY", "label": "Malaysia (MY)"},
]

LAZADA_REGIONS = [
    {"value": "SG", "label": "Singapore (SG)"},
    {"value": "MY", "label": "Malaysia (MY)"},
    {"value": "TH", "label": "Thailand (TH)"},
    {"value": "VN", "label": "Vietnam (VN)"},
    {"value": "ID", "label": "Indonesia (ID)"},
    {"value": "PH", "label": "Philippines (PH)"},
]

COMMON_SECRET_FIELDS = [
    {
        "key": "app_secret",
        "label": "App Secret / Partner Key",
        "type": "password",
        "secret": True,
        "required": False,
        "advanced": False,
        "help_text": "Write-only. The saved value is never returned.",
    },
    {
        "key": "access_token",
        "label": "Access Token",
        "type": "password",
        "secret": True,
        "required": False,
        "advanced": True,
        "help_text": "Advanced migration/recovery only; OAuth normally creates this token.",
    },
    {
        "key": "refresh_token",
        "label": "Refresh Token",
        "type": "password",
        "secret": True,
        "required": False,
        "advanced": True,
        "help_text": "Advanced migration/recovery only; OAuth normally creates this token.",
    },
]

SCHEMAS = {
    "lazada": {
        "label": "Lazada",
        "contract_versions": ["open-platform-v1"],
        "regions": LAZADA_REGIONS,
        "fields": [
            {
                "key": "app_key",
                "label": "App Key",
                "type": "text",
                "required": True,
                "secret": False,
                "help_text": "Public identifier from the approved Lazada Open Platform application.",
            },
            {
                "key": "account_reference",
                "label": "Account / Organization reference",
                "type": "text",
                "required": False,
                "secret": False,
            },
        ],
        "scope_options": [],
        "secret_fields": COMMON_SECRET_FIELDS,
    },
    "shopee": {
        "label": "Shopee",
        "contract_versions": ["v2"],
        "fields": [
            {
                "key": "partner_id",
                "label": "Partner / Application ID",
                "type": "text",
                "required": True,
                "secret": False,
                "help_text": "Public identifier from the approved Shopee application.",
            },
            {
                "key": "merchant_reference",
                "label": "Merchant / Organization reference",
                "type": "text",
                "required": False,
                "secret": False,
            },
        ],
        "scope_options": [],
        "secret_fields": COMMON_SECRET_FIELDS,
    },
    "tiktok": {
        "label": "TikTok Shop",
        "contract_versions": ["202407"],
        "fields": [
            {
                "key": "app_key",
                "label": "App Key / Application ID",
                "type": "text",
                "required": True,
                "secret": False,
                "help_text": "Public identifier from the approved Partner Center application.",
            },
            {
                "key": "service_id",
                "label": "Service ID",
                "type": "text",
                "required": True,
                "secret": False,
                "help_text": "Seller authorization service identifier from the approved Partner Center application.",
            },
            {
                "key": "organization_reference",
                "label": "Organization reference",
                "type": "text",
                "required": False,
                "secret": False,
            },
        ],
        "scope_options": [
            {"value": "seller.authorization.info", "label": "Authorized shop information (read-only)"},
        ],
        "secret_fields": COMMON_SECRET_FIELDS,
    },
}


API_TYPE_OPTIONS = {
    "marketplace": {"value": "marketplace", "label": "商城 API"},
    "advertising": {"value": "advertising", "label": "广告 API"},
    "inventory": {"value": "inventory", "label": "库存 API"},
}

def integration_platform_key(*, platform_type="", code="", name=""):
    """Map a platform master row to the integration contract without using its display name in the UI."""
    platform_type = str(platform_type or "").strip().lower()
    if platform_type in CAPABILITY_REGISTRY:
        return platform_type
    aliases = {
        "lazada": "lazada",
        "shopee": "shopee",
        "tiktok": "tiktok",
        "tiktokshop": "tiktok",
        "myjf": "jifeng_wms",
        "jifengwms": "jifeng_wms",
        "极风wms": "jifeng_wms",
    }
    for candidate in (code, name):
        normalized = "".join(character for character in str(candidate or "").strip().lower() if character.isalnum())
        if normalized in aliases:
            return aliases[normalized]
    return ""


def platform_api_type_options(platform):
    try:
        capability = get_platform_capability(platform)
    except ValidationError:
        return []
    return [API_TYPE_OPTIONS[value].copy() for value in capability.api_types]


def get_platform_schema(platform, *, environment=None, region=None):
    platform = str(platform or "").lower()
    if platform not in SCHEMAS:
        raise ValidationError("Unsupported marketplace platform schema.")
    environment = str(environment or "sandbox").lower()
    if environment not in {"mock", "sandbox", "pilot", "production"}:
        raise ValidationError("Unsupported platform environment.")
    regions = SCHEMAS[platform].get("regions", REGIONS)
    if region and str(region).upper() not in {item["value"] for item in regions}:
        raise ValidationError("Unsupported platform region.")
    return {
        "schema_version": 1,
        "platform": platform,
        "environment": environment,
        "environments": [
            {"value": "mock", "label": "Mock"},
            {"value": "sandbox", "label": "Sandbox"},
            {"value": "pilot", "label": "Pilot"},
            {"value": "production", "label": "Production (approval required)"},
        ],
        "regions": regions,
        "production_write_enabled": False,
        "capabilities": capability_payload(platform),
        **SCHEMAS[platform],
        "public_fields": SCHEMAS[platform]["fields"],
    }


def validate_platform_config(platform, values):
    if not isinstance(values, dict):
        raise ValidationError({"platform_config": "Platform configuration must be an object."})
    schema = get_platform_schema(platform)
    allowed = {field["key"] for field in schema["fields"]}
    secret_keys = {field["key"] for field in schema["secret_fields"]}
    if set(values) & secret_keys:
        raise ValidationError({"platform_config": "Secret fields must use the credential rotation endpoint."})
    unknown = set(values) - allowed
    if unknown:
        raise ValidationError({"platform_config": "Unsupported platform configuration field."})
    for field in schema["fields"]:
        if field.get("required") and not str(values.get(field["key"]) or "").strip():
            raise ValidationError({"platform_config": f"{field['key']} is required."})
    return {key: str(value).strip() for key, value in values.items()}

