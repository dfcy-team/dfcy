"""Select a TK product's expected callback without changing runtime approval."""
from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.exceptions import ValidationError


def expected_oauth_callback(platform, *, callback_url, api_type="marketplace", legacy_callback=""):
    if str(platform or "").lower() != "tiktok":
        return legacy_callback

    from . import tiktok_ads_direct, tiktok_direct_callback

    products = {
        "marketplace": ("TIKTOK_SHOP_DIRECT_CALLBACK_URL", tiktok_direct_callback),
        "advertising": ("TIKTOK_ADS_DIRECT_CALLBACK_URL", tiktok_ads_direct),
    }
    try:
        path = urlsplit(callback_url).path
    except (ValueError, TypeError):
        raise ValidationError("Invalid TikTok callback URL.") from None
    product = products.get(api_type) if isinstance(api_type, str) else None
    configured = getattr(settings, product[0], "") if product else ""
    direct_path = path in {module.CALLBACK_PATH for _, module in products.values()}
    if not direct_path and not (configured and callback_url == configured):
        return legacy_callback
    # A direct-looking URL must never fall back to a legacy/global expectation.
    if (not product or not isinstance(configured, str) or not configured
            or callback_url != product[1].configured_callback()):
        raise ValidationError("TikTok callback does not match this product's direct configuration.")
    return configured
