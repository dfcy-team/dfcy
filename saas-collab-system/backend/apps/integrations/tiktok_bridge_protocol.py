"""Short-lived browser relay envelopes; no TikTok tokens or application secrets."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl, urlsplit

CALLBACK_URI = "https://dingfengchuangyu.com/callback"
START_URI = "https://dingfengchuangyu.com/saas-tk/start"
RETURN_URI = "https://192.168.2.34:8443/integrations/tiktok/authorization-result"
FLOW_FIELDS = ("session_id", "state", "actor_id", "tenant_id", "store_id", "config_id",
               "platform_store_id", "callback_uri", "app_key", "region", "authorization_url", "return_uri")
PURPOSES = {"start": ("saas-vm34", "dfcy-tk-browser", 600),
            "callback": ("dfcy-tk-browser", "saas-vm34", 120)}
RESERVED = {"v", "purpose", "iss", "aud", "iat", "exp"}
DISCOVERY_MODE = "confirm_after_oauth"


class BridgeTokenError(ValueError):
    pass


def _key(value):
    if not isinstance(value, bytes) or len(value) < 32:
        raise BridgeTokenError("BRIDGE_KEY_UNAVAILABLE")
    return value


def _encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
        result[key] = value
    return result


def sign_token(payload, key, purpose, *, now=None, ttl=None):
    if purpose not in PURPOSES or RESERVED.intersection(payload):
        raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
    issuer, audience, maximum = PURPOSES[purpose]
    seconds = maximum if ttl is None else ttl
    if type(seconds) is not int or not 0 < seconds <= maximum:
        raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
    moment = int(time.time() if now is None else now)
    claims = {**payload, "v": 1, "purpose": purpose, "iss": issuer, "aud": audience,
              "iat": moment, "exp": moment + seconds}
    body = _encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    if len(body) > 24000:
        raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
    signature = _encode(hmac.new(_key(key), body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + signature


def verify_token(token, key, purpose, *, now=None):
    try:
        if purpose not in PURPOSES or not isinstance(token, str) or len(token) > 25000:
            raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
        body, signature = token.split(".")
        expected = hmac.new(_key(key), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
        claims = json.loads(_decode(body), object_pairs_hook=_unique)
        issuer, audience, maximum = PURPOSES[purpose]
        moment = int(time.time() if now is None else now)
        if (not isinstance(claims, dict) or type(claims.get("v")) is not int or claims.get("v") != 1 or claims.get("purpose") != purpose
                or claims.get("iss") != issuer or claims.get("aud") != audience
                or type(claims.get("iat")) is not int or type(claims.get("exp")) is not int
                or not 0 < claims["exp"] - claims["iat"] <= maximum
                or claims["iat"] > moment + 30 or claims["exp"] <= moment):
            raise BridgeTokenError("BRIDGE_TOKEN_INVALID")
        return claims
    except BridgeTokenError:
        raise
    except (ValueError, TypeError, UnicodeError, KeyError, OverflowError):
        raise BridgeTokenError("BRIDGE_TOKEN_INVALID") from None


def validate_flow(claims):
    if any(name not in claims for name in FLOW_FIELDS):
        raise BridgeTokenError("BRIDGE_FLOW_INVALID")
    if any(type(claims[name]) is not int or claims[name] <= 0 for name in
           ("session_id", "actor_id", "tenant_id", "store_id", "config_id")):
        raise BridgeTokenError("BRIDGE_FLOW_INVALID")
    binding_mode = claims.get("shop_binding_mode", "bound")
    identifier = claims["platform_store_id"]
    if (not isinstance(binding_mode, str) or binding_mode not in {"bound", DISCOVERY_MODE}
            or not isinstance(identifier, str)
            or (binding_mode == DISCOVERY_MODE and identifier != "")
            or (binding_mode == "bound" and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier))):
        raise BridgeTokenError("BRIDGE_FLOW_INVALID")
    if (claims["callback_uri"] != CALLBACK_URI or claims["return_uri"] != RETURN_URI
            or not isinstance(claims["region"], str) or claims["region"] not in {"PH", "MY", "TH"}
            or not isinstance(claims["state"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", claims["state"])
            or not isinstance(claims["app_key"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", claims["app_key"])):
        raise BridgeTokenError("BRIDGE_FLOW_INVALID")
    try:
        target = urlsplit(claims["authorization_url"])
        pairs = parse_qsl(target.query, keep_blank_values=True, max_num_fields=4)
        params = dict(pairs)
        if (target.scheme != "https" or target.netloc != "services.tiktokshop.com"
                or target.path != "/open/authorize" or target.fragment
                or len(params) != len(pairs) or set(params) != {"service_id", "state"}
                or params["state"] != claims["state"] or not params["service_id"]):
            raise BridgeTokenError("BRIDGE_FLOW_INVALID")
    except (ValueError, TypeError):
        raise BridgeTokenError("BRIDGE_FLOW_INVALID") from None
    return claims


def flow_payload(claims):
    payload = {name: claims[name] for name in FLOW_FIELDS}
    if "shop_binding_mode" in claims:
        payload["shop_binding_mode"] = claims["shop_binding_mode"]
    return payload
