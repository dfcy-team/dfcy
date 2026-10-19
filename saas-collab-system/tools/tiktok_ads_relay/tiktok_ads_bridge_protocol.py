"""Domain-separated Ads relay messages; no application secrets in envelopes."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

CALLBACK_URI = "https://dingfengchuangyu.com/callback"
START_URI = "https://dingfengchuangyu.com/saas-tk-ads/start"
FETCH_URI = "https://dingfengchuangyu.com/saas-tk-ads/receipt"
RETURN_URI = "https://192.168.2.34:8443/integrations/tiktok-ads/authorization-result"
FLOW_FIELDS = ("session_id", "state", "actor_id", "tenant_id", "store_id", "config_id",
               "app_id", "callback_uri", "authorization_url", "return_uri")
PURPOSES = {"start": ("saas-vm34-ads", "dfcy-ads-browser", 600),
            "fetch": ("saas-vm34-ads", "dfcy-ads-receipt", 60)}
RESERVED = {"v", "purpose", "iss", "aud", "iat", "exp"}


class BridgeTokenError(ValueError):
    pass


def derived_key(key, domain=b"dfcy-tiktok-ads-relay-v1"):
    if not isinstance(key, bytes) or len(key) < 32:
        raise BridgeTokenError("ADS_BRIDGE_KEY_UNAVAILABLE")
    return hmac.new(key, domain, hashlib.sha256).digest()


def _encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise BridgeTokenError("ADS_BRIDGE_INVALID")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BridgeTokenError("ADS_BRIDGE_INVALID")
        value[key] = item
    return value


def sign_token(payload, key, purpose, *, now=None, ttl=None):
    if purpose not in PURPOSES or RESERVED.intersection(payload):
        raise BridgeTokenError("ADS_BRIDGE_INVALID")
    issuer, audience, maximum = PURPOSES[purpose]
    ttl = maximum if ttl is None else ttl
    if type(ttl) is not int or not 0 < ttl <= maximum:
        raise BridgeTokenError("ADS_BRIDGE_INVALID")
    moment = int(time.time() if now is None else now)
    claims = {**payload, "v": 1, "purpose": purpose, "iss": issuer, "aud": audience,
              "iat": moment, "exp": moment + ttl}
    body = _encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    if len(body) > 6000:
        raise BridgeTokenError("ADS_BRIDGE_INVALID")
    signature = hmac.new(derived_key(key), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + _encode(signature)


def verify_token(token, key, purpose, *, now=None):
    try:
        if purpose not in PURPOSES or not isinstance(token, str) or len(token) > 6200:
            raise BridgeTokenError("ADS_BRIDGE_INVALID")
        body, signature = token.split(".")
        expected = hmac.new(derived_key(key), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise BridgeTokenError("ADS_BRIDGE_INVALID")
        claims = json.loads(_decode(body), object_pairs_hook=unique_object)
        issuer, audience, maximum = PURPOSES[purpose]
        moment = int(time.time() if now is None else now)
        if (not isinstance(claims, dict) or type(claims.get("v")) is not int or claims["v"] != 1
                or claims.get("purpose") != purpose or claims.get("iss") != issuer or claims.get("aud") != audience
                or type(claims.get("iat")) is not int or type(claims.get("exp")) is not int
                or not 0 < claims["exp"] - claims["iat"] <= maximum
                or claims["iat"] > moment + 30 or claims["exp"] <= moment):
            raise BridgeTokenError("ADS_BRIDGE_INVALID")
        return claims
    except BridgeTokenError:
        raise
    except (ValueError, TypeError, UnicodeError, KeyError, OverflowError):
        raise BridgeTokenError("ADS_BRIDGE_INVALID") from None


def validate_session_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BridgeTokenError("ADS_BRIDGE_INVALID") from None


def validate_flow(claims):
    try:
        if any(field not in claims for field in FLOW_FIELDS):
            raise ValueError
        validate_session_id(claims["session_id"])
        if any(type(claims[name]) is not int or claims[name] <= 0 for name in
               ("actor_id", "tenant_id", "store_id", "config_id")):
            raise ValueError
        if (claims["callback_uri"] != CALLBACK_URI or claims["return_uri"] != RETURN_URI
                or not re.fullmatch(r"saas_ads_[A-Za-z0-9_-]{32,100}", claims["state"])
                or not re.fullmatch(r"[0-9]{5,40}", claims["app_id"])):
            raise ValueError
        parsed = urlsplit(claims["authorization_url"])
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=4)
        params = dict(pairs)
        if (parsed.scheme != "https" or parsed.netloc != "business-api.tiktok.com"
                or parsed.path != "/portal/auth" or parsed.fragment
                or len(params) != len(pairs) or set(params) != {"app_id", "state", "redirect_uri"}
                or params != {"app_id": claims["app_id"], "state": claims["state"], "redirect_uri": CALLBACK_URI}):
            raise ValueError
        return claims
    except (ValueError, TypeError, KeyError):
        raise BridgeTokenError("ADS_BRIDGE_INVALID") from None


def flow_payload(claims):
    return {name: claims[name] for name in FLOW_FIELDS}


def validate_fetch(claims):
    validate_session_id(claims.get("session_id"))
    if (not isinstance(claims.get("receipt_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", claims["receipt_id"])
            or any(type(claims.get(name)) is not int or claims[name] <= 0 for name in
                   ("actor_id", "tenant_id", "store_id", "config_id"))):
        raise BridgeTokenError("ADS_BRIDGE_INVALID")
    return claims
