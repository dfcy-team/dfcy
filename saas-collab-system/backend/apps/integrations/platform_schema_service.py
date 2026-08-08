"""Versioned, non-secret platform configuration schemas for the admin UI."""

from django.core.exceptions import ValidationError


REGIONS = [
    {"value": "PH", "label": "Philippines (PH)"},
    {"value": "TH", "label": "Thailand (TH)"},
    {"value": "MY", "label": "Malaysia (MY)"},
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


def get_platform_schema(platform, *, environment=None, region=None):
    platform = str(platform or "").lower()
    if platform not in SCHEMAS:
        raise ValidationError("Unsupported marketplace platform schema.")
    environment = str(environment or "sandbox").lower()
    if environment not in {"mock", "sandbox", "pilot", "production"}:
        raise ValidationError("Unsupported platform environment.")
    if region and str(region).upper() not in {item["value"] for item in REGIONS}:
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
        "regions": REGIONS,
        "production_write_enabled": False,
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
