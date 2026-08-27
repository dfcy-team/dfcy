from copy import deepcopy

from django.core.exceptions import ValidationError


INVENTORY_SNAPSHOT_CONTRACT_VERSION = "inventory_snapshot.v1"
ALLOWED_SITES = {"PH", "TH", "MY"}
FORBIDDEN_CREDENTIAL_KEYS = {
    "app_secret",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "secret_key",
    "sign",
    "cookie",
}


def _reject_credentials(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_CREDENTIAL_KEYS:
                raise ValidationError("Credential material is not accepted by the inventory contract.")
            _reject_credentials(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_credentials(nested)


def _required(payload, key):
    value = payload.get(key)
    if value in (None, ""):
        raise ValidationError(f"Missing required normalized inventory field: {key}")
    return value


def normalize_inventory_snapshot_record(record):
    _reject_credentials(record)
    payload = deepcopy(record)
    if payload.get("contract_version") != INVENTORY_SNAPSHOT_CONTRACT_VERSION:
        raise ValidationError("Unsupported or missing inventory contract version.")
    site_code = str(_required(payload, "site_code")).upper()
    if site_code not in ALLOWED_SITES:
        raise ValidationError("Inventory site must be PH, TH, or MY.")
    quantities = {}
    for field in (
        "on_hand_qty",
        "available_qty",
        "reserved_qty",
        "in_transit_qty",
        "pending_putaway_qty",
        "defective_qty",
    ):
        value = int(payload.get(field) or 0)
        if value < 0:
            raise ValidationError(f"{field} cannot be negative.")
        quantities[field] = value
    return {
        "site_code": site_code,
        "warehouse_id": str(_required(payload, "warehouse_id")),
        "source_sku": str(_required(payload, "source_sku")),
        "platform_product_id": str(payload.get("platform_product_id") or ""),
        "platform_variant_id": str(payload.get("platform_variant_id") or ""),
        "seller_sku": str(payload.get("seller_sku") or ""),
        "snapshot_at_utc": _required(payload, "snapshot_at_utc"),
        **quantities,
    }
