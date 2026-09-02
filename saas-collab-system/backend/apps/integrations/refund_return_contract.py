from copy import deepcopy

from django.core.exceptions import ValidationError

from .models import PlatformChoices


REFUND_RETURN_CONTRACT_VERSION = "refund_return.v1"
SUPPORTED_PLATFORMS = {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
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
                raise ValidationError("Platform credential material is not accepted by the refund contract.")
            _reject_credentials(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_credentials(nested)


def _required(payload, key):
    value = payload.get(key)
    if value in (None, ""):
        raise ValidationError(f"Missing required normalized refund field: {key}")
    return value


def normalize_refund_return_record(platform, record):
    platform = str(platform).lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValidationError("Unsupported refund platform contract.")
    _reject_credentials(record)
    payload = deepcopy(record)
    if payload.get("contract_version") != REFUND_RETURN_CONTRACT_VERSION:
        raise ValidationError("Unsupported or missing refund contract version.")
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValidationError("Normalized refund items must be a list.")
    currency = str(_required(payload, "currency")).upper()
    return {
        "platform": platform,
        "store_id": str(_required(payload, "store_id")),
        "external_return_id": str(_required(payload, "external_return_id")),
        "external_refund_id": str(payload.get("external_refund_id") or ""),
        "external_order_id": str(payload.get("external_order_id") or ""),
        "case_type": str(_required(payload, "case_type")),
        "raw_status": str(_required(payload, "raw_status")),
        "normalized_status": str(_required(payload, "normalized_status")).lower(),
        "arbitration_status": str(payload.get("arbitration_status") or ""),
        "reason_code": str(payload.get("reason_code") or ""),
        "requested_at_utc": _required(payload, "requested_at_utc"),
        "updated_at_utc": _required(payload, "updated_at_utc"),
        "completed_at_utc": payload.get("completed_at_utc"),
        "currency": currency,
        "refund_amount": str(payload.get("refund_amount") or "0"),
        "refund_subtotal": str(payload.get("refund_subtotal") or "0"),
        "refund_shipping_fee": str(payload.get("refund_shipping_fee") or "0"),
        "refund_tax": str(payload.get("refund_tax") or "0"),
        "requires_physical_return": payload.get("requires_physical_return"),
        "is_partial_quantity_return": payload.get("is_partial_quantity_return"),
        "is_refund_amount_adjusted": payload.get("is_refund_amount_adjusted"),
        "items": [
            {
                "external_return_item_id": str(_required(item, "external_return_item_id")),
                "external_order_item_id": str(item.get("external_order_item_id") or ""),
                "platform_product_id": str(item.get("platform_product_id") or ""),
                "platform_variant_id": str(item.get("platform_variant_id") or ""),
                "seller_sku": str(item.get("seller_sku") or ""),
                "item_name_snapshot": str(item.get("item_name_snapshot") or ""),
                "quantity": int(item.get("quantity") or 0),
                "currency": str(item.get("currency") or currency).upper(),
                "refund_amount": str(item.get("refund_amount") or "0"),
            }
            for item in items
        ],
    }
