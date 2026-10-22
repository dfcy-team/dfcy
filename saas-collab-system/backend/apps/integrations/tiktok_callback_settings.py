"""Resolve approved web configuration before legacy deployment settings."""
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .production_settings import runtime_snapshot


def callback_setting(advertising=False):
    key = "ads_direct_callback_url" if advertising else "shop_direct_callback_url"
    snapshot = runtime_snapshot()
    if snapshot.get("source", "").startswith("invalid"):
        raise ValidationError("Invalid approved runtime configuration; direct authorization is disabled.")
    config = snapshot["config"]
    platform = config.get("platforms", {}).get("tiktok", {})
    if key in platform:
        value = platform[key]
        if value and value not in config.get("network", {}).get("oauth_redirect_allowlist", []):
            raise ValidationError("TK direct callback must be in the approved OAuth redirect allowlist.")
        # Explicit empty values disable direct authorization; never revive an env value.
        return value
    name = "TIKTOK_ADS_DIRECT_CALLBACK_URL" if advertising else "TIKTOK_SHOP_DIRECT_CALLBACK_URL"
    return getattr(settings, name, "")
