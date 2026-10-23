"""Browser-bound Ads callbacks, independent from the legacy relay."""
import hmac
import re
from urllib.parse import urlsplit

from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import ValidationError

SALT = "tiktok-ads-direct-callback-v1"
PURPOSE = "tiktok_ads_direct"
CALLBACK_PATH = "/integrations/tiktok-ads/direct-callback"


def configured_callback():
    from .tiktok_callback_settings import callback_setting
    value = callback_setting(advertising=True)
    if value == "":
        return ""
    try:
        parsed = urlsplit(value)
        valid = (isinstance(value, str) and parsed.scheme == "https" and parsed.hostname
            and parsed.path == CALLBACK_PATH and not parsed.query and not parsed.fragment
            and "?" not in value and "#" not in value and "@" not in parsed.netloc
            and not parsed.username and not parsed.password and "\\" not in value
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not any(ord(c) <= 32 or ord(c) == 127 for c in value))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValidationError("Invalid Ads direct callback configuration; no relay fallback.")
    return value


def claims_for(session):
    return {"purpose": PURPOSE, "actor_id": session.actor_id, "tenant_id": session.tenant_id,
        "session_id": str(session.pk), "store_id": session.store_id,
        "config_id": session.integration_config_id, "region": session.store.country_code,
        "environment": session.integration_config.environment,
        "fingerprint": session.config_fingerprint, "callback_url": session.integration_config.callback_url,
        "expires_at": int(session.expires_at.timestamp())}


def valid_verifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is not None


def prepare(session, verifier):
    from .tiktok_ads_oauth import digest
    if not valid_verifier(verifier):
        raise ValidationError("A fresh browser verifier is required for Ads direct authorization.")
    session.browser_verifier_hash = digest(verifier)
    session.callback_transport = "direct"
    return {"browser_token": signing.dumps(claims_for(session), salt=SALT),
        "callback_url": session.integration_config.callback_url, "expires_at": session.expires_at}


def complete(actor, browser_token, browser_verifier, callback_params):
    from . import tiktok_ads_oauth as ads
    try:
        if not isinstance(browser_token, str) or len(browser_token) > 8192:
            raise ValueError
        claims = signing.loads(browser_token, salt=SALT, max_age=600)
        if not isinstance(claims, dict) or claims.get("purpose") != PURPOSE:
            raise ValueError
        if claims.get("actor_id") != actor.pk or claims.get("tenant_id") != actor.tenant_id:
            raise ValueError
        # Parse a UUID before allowing it to reach the ORM.
        from uuid import UUID
        session_id = UUID(claims["session_id"])
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        raise ValidationError("Invalid or expired Ads browser token.") from None

    def validate(session):
        params = callback_params
        if (claims != claims_for(session) or not configured_callback()
                or claims["callback_url"] != configured_callback()
                or claims["expires_at"] <= timezone.now().timestamp()
                or session.callback_transport != "direct" or not valid_verifier(browser_verifier)
                or not session.browser_verifier_hash
                or not hmac.compare_digest(session.browser_verifier_hash, ads.digest(browser_verifier))
                or not isinstance(params, dict) or set(params) - {"auth_code", "code", "state", "error", "id"}
                or any(not isinstance(v, str) or len(v) > 8192
                    or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in params.values())
                or not params.get("state") or not params["state"].strip()
                or not hmac.compare_digest(ads.digest(params["state"]), session.state_hash)):
            raise ValidationError("Ads callback does not match this browser session.")
        if "id" in params and (not re.fullmatch(r"[0-9]{5,40}", params["id"])
                or params["id"] != str(session.integration_config.platform_config.get("app_id", ""))):
            raise ValidationError("Ads callback application does not match this session.")
        # TikTok documents auth_code as authoritative even when code also exists.
        code = params.get("auth_code", params.get("code", ""))
        if (params.get("error") and (params["error"] != "authorization_denied" or code)
                or not params.get("error") and not code.strip()):
            raise ValidationError("Invalid Ads authorization result.")
        return {"state": params["state"], "auth_code": code,
                **({"error": params["error"]} if params.get("error") else {})}

    return ads._complete(actor, session_id, direct_validator=validate)
