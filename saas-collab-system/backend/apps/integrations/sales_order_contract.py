from copy import deepcopy

from django.core.exceptions import ValidationError

from .models import PlatformChoices


SALES_ORDER_CONTRACT_VERSION = "sales_order.v1"
SUPPORTED_PLATFORMS = {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
NORMALIZED_ORDER_STATUSES = {"pending", "confirmed", "fulfilled", "completed", "cancelled"}
FORBIDDEN_CREDENTIAL_KEYS = {
    "app_secret",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
    "secret_key",
}


def _reject_credentials(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_CREDENTIAL_KEYS:
                raise ValidationError("Platform credential material is not accepted by the sales order contract.")
            _reject_credentials(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_credentials(nested)


def _required(payload, key):
    value = payload.get(key)
    if value in (None, ""):
        raise ValidationError(f"Missing required normalized sales order field: {key}")
    return value


def normalize_sales_order_record(platform, record):
    """Validate the canonical sales-order record emitted by the integrations boundary.

    Platform-specific response fields and statuses must be mapped by the owning
    integration adapter before this contract is called. Sales management never
    interprets raw Shopee or TikTok Shop response payloads.
    """
    platform = str(platform).lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValidationError("Unsupported sales platform contract.")
    _reject_credentials(record)
    payload = deepcopy(record)
    if payload.get("contract_version") != SALES_ORDER_CONTRACT_VERSION:
        raise ValidationError("Unsupported or missing sales order contract version.")
    order_status = str(payload.get("order_status") or "pending").lower()
    if order_status not in NORMALIZED_ORDER_STATUSES:
        raise ValidationError("Order status must already be normalized by the integration adapter.")
    source_order_id = str(_required(payload, "source_order_id"))
    lines = payload.get("lines") or []
    if not isinstance(lines, list):
        raise ValidationError("Normalized sales order lines must be a list.")

    return {
        "platform": platform,
        "region": str(payload.get("region") or ""),
        "store_id": str(_required(payload, "store_id")),
        "source_order_id": source_order_id,
        "system_order_no": str(payload.get("system_order_no") or source_order_id),
        "ordered_at": _required(payload, "ordered_at"),
        "source_updated_at": _required(payload, "source_updated_at"),
        "currency": str(_required(payload, "currency")).upper(),
        "gross_amount": str(_required(payload, "gross_amount")),
        "net_amount": str(payload.get("net_amount") or payload["gross_amount"]),
        "discount_amount": str(payload.get("discount_amount") or "0"),
        "tax_amount": str(payload.get("tax_amount") or "0"),
        "shipping_amount": str(payload.get("shipping_amount") or "0"),
        "buyer_region": str(payload.get("buyer_region") or ""),
        "order_status": order_status,
        "fulfillment_status": str(payload.get("fulfillment_status") or "pending").lower(),
        "refund_status": str(payload.get("refund_status") or "none").lower(),
        "lines": [
            {
                "source_line_id": str(_required(item, "source_line_id")),
                "spu": str(item.get("spu") or ""),
                "sku": str(_required(item, "sku")),
                "product_name": str(item.get("product_name") or ""),
                "quantity": int(item.get("quantity") or 0),
                "unit_price": str(item.get("unit_price") or "0"),
                "discount_amount": str(item.get("discount_amount") or "0"),
                "tax_amount": str(item.get("tax_amount") or "0"),
                "shipping_amount": str(item.get("shipping_amount") or "0"),
                "source_updated_at": payload["source_updated_at"],
            }
            for item in lines
        ],
    }
