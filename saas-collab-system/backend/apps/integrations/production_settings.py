"""Versioned production runtime settings for marketplace integrations.

The values in this module are deliberately non-sensitive.  A system
administrator can version and approve network, endpoint and feature-gate
settings through :mod:`apps.configcenter`; credentials themselves remain in
the independent custody boundary and are represented only by mounted file
paths or references.

The read path is fail-closed: an invalid effective database version never
enables a live capability.  Environment variables are retained as a
compatibility fallback only when no valid effective database version exists.
"""

from __future__ import annotations

from copy import deepcopy
import ipaddress
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone


CONFIG_KEY = "integrations.production.runtime"
LIVE_NETWORK_MODE = "approved-live-test"
LISTING_WRITE_PLATFORMS = frozenset({"lazada", "shopee", "tiktok"})
LISTING_WRITE_ACTIONS = frozenset({"create", "update", "pause"})
LISTING_WRITE_MODES = frozenset({"disabled", "controlled"})
MODULE_STATES = frozenset({"disabled", "mock_only", "pilot_readonly", "enabled"})
MODULE_CODES = (
    "core", "masterdata", "product_development", "supply_chain", "inventory",
    "global_listing", "sales", "influencer", "finance", "analytics", "decision",
    "reports", "workflow", "rpa", "api_integrations", "system", "governance",
)


SAFE_DEFAULTS = {
    # Pre-module-switch configurations remain compatible by enabling every
    # module until an administrator explicitly creates an approved allowlist.
    "modules": {code: "enabled" for code in MODULE_CODES},
    "network": {
        "mode": "",
        "security_approved": False,
        "readonly_sync_enabled": False,
        "allowed_hosts": [],
        "oauth_redirect_allowlist": [],
    },
    "connection": {
        "connect_timeout_seconds": 3.0,
        "read_timeout_seconds": 8.0,
        "max_retries": 2,
        "backoff_base_seconds": 0.5,
        "max_retry_wait_seconds": 8.0,
        "max_total_wait_seconds": 15.0,
    },
    "custody": {
        "backend": "refuse",
        "service_url": "",
        "service_host": "",
        "auth_file_path": "",
        "ca_file_path": "",
    },
    # Listing publication is deliberately a separate capability from API
    # synchronisation.  An empty store/platform/action allowlist and the
    # emergency stop make the safe state unambiguously fail closed.
    "listing_write": {
        "mode": "disabled",
        "emergency_stop": True,
        "require_batch_approval": True,
        "allowed_platforms": [],
        "allowed_actions": [],
        "allowed_store_ids": [],
        "max_batch_size": 20,
    },
    "platforms": {
        "lazada": {
            "contract_approved": False,
            "app_id": "",
            "redirect_uri": "",
            "auth_url": "https://auth.lazada.com/oauth/authorize",
            "api_host": "https://api.lazada.com",
            "token_path": "/rest/auth/token/create",
            "refresh_path": "/rest/auth/token/refresh",
            "market": "",
        },
        "shopee": {
            "contract_approved": False,
            "app_id": "",
            "redirect_uri": "",
            "auth_url": "https://partner.shopeemobile.com/api/v2/shop/auth_partner",
            "api_host": "https://partner.shopeemobile.com",
            "token_path": "/api/v2/auth/token/get",
            "refresh_path": "/api/v2/auth/access_token/get",
            "revoke_path": "/api/v2/shop/cancel_auth_partner",
            "shop_path": "/api/v2/shop/get_shop_info",
            "order_list_path": "/api/v2/order/get_order_list",
            "order_detail_path": "/api/v2/order/get_order_detail",
            "return_list_path": "/api/v2/returns/get_return_list",
            "return_detail_path": "/api/v2/returns/get_return_detail",
            "market": "",
            "region": "",
        },
        "tiktok": {
            "contract_approved": False,
            "app_id": "",
            "service_id": "",
            "redirect_uri": "",
            "market": "ROW",
            "auth_url": "",
            "api_host": "",
            "auth_urls": {},
            "api_hosts": {},
            "token_host": "https://auth.tiktok-shops.com",
            "token_path": "/api/v2/token/get",
            "refresh_path": "/api/v2/token/refresh",
            "revoke_path": "",
            "authorized_shops_path": "/authorization/202309/shops",
            "metadata_path": "/seller/202309/permissions",
            "order_list_path": "/order/202309/orders/search",
            "order_detail_path": "/order/202309/orders",
            "return_list_path": "/return_refund/202602/returns/search",
        },
    },
}


_SAFE_ENDPOINT_KEYS = {
    "token_host",
    "token_path",
    "refresh_path",
    "revoke_path",
    "authorized_shops_path",
    "metadata_path",
}
_SAFE_PATH_KEYS = _SAFE_ENDPOINT_KEYS - {"token_host"}
_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "cookie",
    "session",
    "access_token",
    "refresh_token",
    "token",
    "credential",
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(password|passwd|access[_-]?token|refresh[_-]?token|api[_-]?secret|client[_-]?secret|app[_-]?secret)\s*[:=]"
)
_PLATFORM_KEYS = {"lazada", "shopee", "tiktok"}
_TOP_LEVEL_KEYS = {"modules", "network", "connection", "custody", "listing_write", "platforms"}
_MODULE_KEYS = set(MODULE_CODES)
_NETWORK_KEYS = {
    "mode",
    "security_approved",
    "readonly_sync_enabled",
    "allowed_hosts",
    "oauth_redirect_allowlist",
}
_CONNECTION_KEYS = {
    "connect_timeout_seconds",
    "read_timeout_seconds",
    "max_retries",
    "backoff_base_seconds",
    "max_retry_wait_seconds",
    "max_total_wait_seconds",
}
_CUSTODY_KEYS = {"backend", "service_url", "service_host", "auth_file_path", "ca_file_path"}
_LISTING_WRITE_KEYS = {
    "mode",
    "emergency_stop",
    "require_batch_approval",
    "allowed_platforms",
    "allowed_actions",
    "allowed_store_ids",
    "max_batch_size",
}
_PLATFORM_COMMON_KEYS = {"contract_approved", "app_id", "service_id", "redirect_uri", "market"}
_PLATFORM_KEYS_BY_NAME = {
    "lazada": _PLATFORM_COMMON_KEYS | {"auth_url", "api_host", "token_path", "refresh_path"},
        "shopee": _PLATFORM_COMMON_KEYS | {
        "auth_url", "api_host", "token_path", "refresh_path", "revoke_path", "shop_path", "region",
        "order_list_path", "order_detail_path", "return_list_path", "return_detail_path",
    },
    "tiktok": _PLATFORM_COMMON_KEYS | {
        "auth_url", "api_host", "auth_urls", "api_hosts", "token_host", "token_path", "refresh_path",
        "revoke_path", "authorized_shops_path", "metadata_path", "order_list_path", "order_detail_path",
        "return_list_path",
    },
}


def _raise(path: str, message: str):
    raise ValidationError({path: message})


def _require_mapping(value: Any, path: str):
    if not isinstance(value, dict):
        _raise(path, "must be an object")


def _check_no_plaintext_secret(value: Any, path="runtime"):
    """Reject credential material while allowing endpoint path names."""
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            if not key:
                _raise(path, "keys must not be empty")
            if key not in _SAFE_ENDPOINT_KEYS and any(part in key for part in _FORBIDDEN_KEY_PARTS):
                _raise(f"{path}.{raw_key}", "credential/token values are not allowed; use custody references or paths")
            _check_no_plaintext_secret(item, f"{path}.{raw_key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_no_plaintext_secret(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and _ASSIGNMENT_PATTERN.search(value):
        _raise(path, "credential/token assignments are not allowed")


def _string(value: Any, path: str, *, allow_empty=True, max_length=200):
    if not isinstance(value, str):
        _raise(path, "must be a string")
    value = value.strip()
    if not allow_empty and not value:
        _raise(path, "must not be empty")
    if len(value) > max_length:
        _raise(path, f"must not exceed {max_length} characters")
    if "\x00" in value or any(ord(char) < 32 for char in value if char not in "\t"):
        _raise(path, "contains control characters")
    return value


def _boolean(value: Any, path: str):
    if not isinstance(value, bool):
        _raise(path, "must be boolean")
    return value


def _host(value: Any, path: str):
    value = _string(value, path, allow_empty=False, max_length=253).lower().rstrip(".")
    if any(char.isspace() for char in value) or "/" in value or "://" in value or ":" in value:
        _raise(path, "must be a hostname without scheme, port or path")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if len(value) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
        _raise(path, "is not a valid hostname")
    labels = value.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        _raise(path, "is not a valid hostname")
    return value


def _https_url(value: Any, path: str, *, allow_empty=True, strip_trailing_slash=True):
    value = _string(value, path, allow_empty=allow_empty, max_length=500)
    # Redirect URIs are path-sensitive: a registered callback ending in `/`
    # is not interchangeable with the same URL without it.  Endpoint/base
    # URLs keep the historical normalization, while allowlists and platform
    # redirect_uri values preserve the operator-supplied trailing slash.
    if strip_trailing_slash:
        value = value.rstrip("/")
    if not value:
        return value
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _raise(path, "is not a valid URL")
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port is not None and not 1 <= port <= 65535
    ):
        _raise(path, "must be an HTTPS URL without credentials or fragments")
    _host(parsed.hostname, path)
    return value


def _path(value: Any, path: str, *, allow_empty=True):
    value = _string(value, path, allow_empty=allow_empty, max_length=255)
    if not value:
        return value
    if not value.startswith("/") or "//" in value or "://" in value or "?" in value or "#" in value:
        _raise(path, "must be an absolute API path without query, fragment or URL scheme")
    return value


def _file_path(value: Any, path: str):
    value = _string(value, path, allow_empty=True, max_length=500)
    if not value:
        return value
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or "\x00" in value:
        _raise(path, "must be an absolute mounted file path")
    return str(candidate)


def _list(value: Any, path: str, *, item_kind: str, max_items=200):
    if not isinstance(value, list):
        _raise(path, "must be an array")
    if len(value) > max_items:
        _raise(path, f"must contain at most {max_items} items")
    result = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if item_kind == "host":
            result.append(_host(item, item_path))
        elif item_kind == "url":
            result.append(_https_url(item, item_path, allow_empty=False, strip_trailing_slash=False))
        else:
            result.append(_string(item, item_path, allow_empty=False, max_length=500))
    if len(result) != len(set(result)):
        _raise(path, "must not contain duplicates")
    return result


def _enum_list(value: Any, path: str, *, allowed: set[str], max_items: int):
    """Validate a bounded, case-insensitive enum allowlist.

    Duplicate entries are rejected instead of silently collapsed.  This keeps
    an operator's submitted version auditable and prevents a malformed UI
    payload from looking like a different policy after normalization.
    """
    if not isinstance(value, list):
        _raise(path, "must be an array")
    if len(value) > max_items:
        _raise(path, f"must contain at most {max_items} items")
    result = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        normalized = _string(item, item_path, allow_empty=False, max_length=40).lower()
        if normalized not in allowed:
            _raise(item_path, f"unsupported value; allowed values are {', '.join(sorted(allowed))}")
        result.append(normalized)
    if len(result) != len(set(result)):
        _raise(path, "must not contain duplicates")
    return result


def _positive_integer_list(value: Any, path: str, *, max_items: int):
    """Validate a bounded allowlist of positive integer database IDs."""
    if not isinstance(value, list):
        _raise(path, "must be an array")
    if len(value) > max_items:
        _raise(path, f"must contain at most {max_items} items")
    result = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            _raise(f"{path}[{index}]", "must be a positive integer")
        result.append(item)
    if len(result) != len(set(result)):
        _raise(path, "must not contain duplicates")
    return result


def _validate_mapping_keys(value: dict, allowed: set[str], path: str):
    unknown = set(value) - allowed
    if unknown:
        _raise(path, f"unsupported fields: {', '.join(sorted(str(item) for item in unknown))}")


def validate_runtime_config(value: Any):
    """Validate a stored or submitted runtime config and return a copy.

    Partial objects are accepted so an administrator can create a version for
    one section; runtime loading merges it over safe/environment defaults.
    """
    _require_mapping(value, "runtime")
    _check_no_plaintext_secret(value)
    _validate_mapping_keys(value, _TOP_LEVEL_KEYS, "runtime")
    result = deepcopy(value)

    if "modules" in value:
        modules = value["modules"]
        _require_mapping(modules, "modules")
        unknown = set(modules) - _MODULE_KEYS
        if unknown:
            _raise("modules", f"unsupported module code(s): {', '.join(sorted(unknown))}")
        for code, state in modules.items():
            if state not in MODULE_STATES:
                _raise(f"modules.{code}", f"must be one of: {', '.join(sorted(MODULE_STATES))}")
            result["modules"][code] = state

    if "network" in value:
        network = value["network"]
        _require_mapping(network, "network")
        _validate_mapping_keys(network, _NETWORK_KEYS, "network")
        if "mode" in network:
            mode = _string(network["mode"], "network.mode", max_length=40)
            if mode not in {"", LIVE_NETWORK_MODE}:
                _raise("network.mode", "must be empty or approved-live-test")
            result["network"]["mode"] = mode
        for key in ("security_approved", "readonly_sync_enabled"):
            if key in network:
                result["network"][key] = _boolean(network[key], f"network.{key}")
        if "allowed_hosts" in network:
            result["network"]["allowed_hosts"] = _list(network["allowed_hosts"], "network.allowed_hosts", item_kind="host")
        if "oauth_redirect_allowlist" in network:
            result["network"]["oauth_redirect_allowlist"] = _list(
                network["oauth_redirect_allowlist"], "network.oauth_redirect_allowlist", item_kind="url"
            )

    if "connection" in value:
        connection = value["connection"]
        _require_mapping(connection, "connection")
        _validate_mapping_keys(connection, _CONNECTION_KEYS, "connection")
        for key in ("connect_timeout_seconds", "read_timeout_seconds", "backoff_base_seconds", "max_retry_wait_seconds", "max_total_wait_seconds"):
            if key in connection:
                item = connection[key]
                if isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0:
                    _raise(f"connection.{key}", "must be a positive number")
                upper = 10 if key == "connect_timeout_seconds" else 30 if key == "read_timeout_seconds" else 60
                if float(item) > upper:
                    _raise(f"connection.{key}", f"must not exceed {upper}")
                result["connection"][key] = float(item)
        if "max_retries" in connection:
            item = connection["max_retries"]
            if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 5:
                _raise("connection.max_retries", "must be an integer between 0 and 5")
            result["connection"]["max_retries"] = item

    if "custody" in value:
        custody = value["custody"]
        _require_mapping(custody, "custody")
        _validate_mapping_keys(custody, _CUSTODY_KEYS, "custody")
        if "backend" in custody:
            backend = _string(custody["backend"], "custody.backend", max_length=20).lower()
            if backend not in {"refuse", "http", "file"}:
                _raise("custody.backend", "must be refuse, http or file")
            result["custody"]["backend"] = backend
        if "service_url" in custody:
            result["custody"]["service_url"] = _https_url(custody["service_url"], "custody.service_url")
        if "service_host" in custody and custody["service_host"]:
            result["custody"]["service_host"] = _host(custody["service_host"], "custody.service_host")
        for key in ("auth_file_path", "ca_file_path"):
            if key in custody:
                result["custody"][key] = _file_path(custody[key], f"custody.{key}")
        service_url = result.get("custody", {}).get("service_url", "")
        service_host = result.get("custody", {}).get("service_host", "")
        if service_url and service_host:
            parsed_host = urlsplit(service_url).hostname or ""
            if parsed_host.lower().rstrip(".") != service_host.lower().rstrip("."):
                _raise("custody.service_host", "must match custody.service_url hostname")

    if "listing_write" in value:
        listing_write = value["listing_write"]
        _require_mapping(listing_write, "listing_write")
        _validate_mapping_keys(listing_write, _LISTING_WRITE_KEYS, "listing_write")
        if "mode" in listing_write:
            mode = _string(listing_write["mode"], "listing_write.mode", allow_empty=False, max_length=20).lower()
            if mode not in LISTING_WRITE_MODES:
                _raise("listing_write.mode", "must be disabled or controlled")
            result["listing_write"]["mode"] = mode
        for key in ("emergency_stop", "require_batch_approval"):
            if key in listing_write:
                result["listing_write"][key] = _boolean(listing_write[key], f"listing_write.{key}")
        if (
            result.get("listing_write", {}).get("mode") == "controlled"
            and "require_batch_approval" in listing_write
            and listing_write["require_batch_approval"] is not True
        ):
            _raise("listing_write.require_batch_approval", "controlled mode requires per-batch approval")
        if "allowed_platforms" in listing_write:
            result["listing_write"]["allowed_platforms"] = _enum_list(
                listing_write["allowed_platforms"],
                "listing_write.allowed_platforms",
                allowed=LISTING_WRITE_PLATFORMS,
                max_items=len(LISTING_WRITE_PLATFORMS),
            )
        if "allowed_actions" in listing_write:
            result["listing_write"]["allowed_actions"] = _enum_list(
                listing_write["allowed_actions"],
                "listing_write.allowed_actions",
                allowed=LISTING_WRITE_ACTIONS,
                max_items=len(LISTING_WRITE_ACTIONS),
            )
        if "allowed_store_ids" in listing_write:
            result["listing_write"]["allowed_store_ids"] = _positive_integer_list(
                listing_write["allowed_store_ids"],
                "listing_write.allowed_store_ids",
                max_items=500,
            )
        if "max_batch_size" in listing_write:
            batch_size = listing_write["max_batch_size"]
            if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
                _raise("listing_write.max_batch_size", "must be an integer between 1 and 100")
            result["listing_write"]["max_batch_size"] = batch_size

    if "platforms" in value:
        platforms = value["platforms"]
        _require_mapping(platforms, "platforms")
        _validate_mapping_keys(platforms, _PLATFORM_KEYS, "platforms")
        for platform, item in platforms.items():
            path = f"platforms.{platform}"
            _require_mapping(item, path)
            _validate_mapping_keys(item, _PLATFORM_KEYS_BY_NAME[platform], path)
            if "contract_approved" in item:
                result["platforms"][platform]["contract_approved"] = _boolean(item["contract_approved"], f"{path}.contract_approved")
            for key in ("app_id", "service_id", "market", "region"):
                if key in item:
                    result["platforms"][platform][key] = _string(item[key], f"{path}.{key}", max_length=120)
            if "redirect_uri" in item:
                result["platforms"][platform]["redirect_uri"] = _https_url(
                    item["redirect_uri"], f"{path}.redirect_uri", strip_trailing_slash=False
                )
            for key in ("auth_url", "api_host", "token_host"):
                if key in item:
                    result["platforms"][platform][key] = _https_url(item[key], f"{path}.{key}")
            for key in _SAFE_PATH_KEYS | {"shop_path", "order_list_path", "order_detail_path", "return_list_path", "return_detail_path"}:
                if key in item:
                    result["platforms"][platform][key] = _path(item[key], f"{path}.{key}")
            for key in ("auth_urls", "api_hosts"):
                if key in item:
                    mapping = item[key]
                    _require_mapping(mapping, f"{path}.{key}")
                    if len(mapping) > 50:
                        _raise(f"{path}.{key}", "contains too many market entries")
                    normalized = {}
                    for market, endpoint in mapping.items():
                        market_key = _string(market, f"{path}.{key}", allow_empty=False, max_length=40).upper()
                        normalized[market_key] = _https_url(endpoint, f"{path}.{key}.{market_key}", allow_empty=False)
                    result["platforms"][platform][key] = normalized
    return result


def _deep_merge(base: dict, override: dict):
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _env_bool(name: str, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _setting(name: str, default=None):
    try:
        from django.conf import settings

        return getattr(settings, name, default)
    except Exception:
        return default


def _configured_or_empty(value):
    """Treat deployment placeholders as an intentionally unconfigured value."""
    value = str(value or "").strip()
    return "" if value.startswith("REPLACE_ME") else value


def _environment_config():
    """Build the legacy settings projection without reading any secret value."""
    auth_urls = _setting("LIVE_TIKTOK_AUTH_URLS", {}) or {}
    api_hosts = _setting("LIVE_TIKTOK_OPEN_API_HOSTS", {}) or {}
    configured_modules = list(_setting("ENABLED_MODULES", []) or [])
    if not configured_modules and bool(_setting("DEBUG", False)):
        profile = str(_setting("LOCAL_SANDBOX_MODULE", "") or "").strip().lower()
        profile_modules = {
            "core": {"core", "masterdata", "system", "governance"},
            "sales-inventory-finance-reconciliation": {"core", "masterdata", "sales", "inventory", "finance", "analytics", "decision", "reports"},
            "creator-management": {"core", "masterdata", "influencer"},
            "procurement": {"core", "masterdata", "supply_chain"},
            "integration": set(MODULE_CODES),
        }
        configured_modules = sorted(profile_modules.get(profile, set()))
    payload = {
        "network": {
            "mode": _setting("PLATFORM_NETWORK_MODE", "") or "",
            "security_approved": bool(_setting("LIVE_PLATFORM_SECURITY_APPROVED", False)),
            "readonly_sync_enabled": bool(_setting("LIVE_READONLY_SYNC_ENABLED", False)),
            "allowed_hosts": list(_setting("LIVE_PLATFORM_ALLOWED_HOSTS", []) or []),
            "oauth_redirect_allowlist": list(_setting("LIVE_OAUTH_REDIRECT_ALLOWLIST", []) or []),
        },
        "connection": {
            "connect_timeout_seconds": _setting("LIVE_PLATFORM_CONNECT_TIMEOUT", 3),
            "read_timeout_seconds": _setting("LIVE_PLATFORM_READ_TIMEOUT", 8),
            "max_retries": _setting("LIVE_PLATFORM_MAX_RETRIES", 2),
            "backoff_base_seconds": _setting("LIVE_PLATFORM_BACKOFF_BASE", 0.5),
            "max_retry_wait_seconds": _setting("LIVE_PLATFORM_MAX_RETRY_WAIT", 8),
            "max_total_wait_seconds": _setting("LIVE_PLATFORM_MAX_TOTAL_WAIT", 15),
        },
        "custody": {
            "backend": _setting("LIVE_CUSTODY_BACKEND", "refuse"),
            "service_url": _setting("LIVE_CUSTODY_SERVICE_URL", "") or "",
            "service_host": _setting("LIVE_CUSTODY_SERVICE_HOST", "") or "",
            "auth_file_path": _setting("LIVE_CUSTODY_SERVICE_TOKEN_FILE", "") or _setting("LIVE_CUSTODY_SERVICE_AUTH_TOKEN_FILE", "") or "",
            "ca_file_path": _setting("LIVE_CUSTODY_CA_FILE", "") or "",
        },
        "platforms": {
            "lazada": {
                "contract_approved": bool(_setting("LIVE_LAZADA_CONTRACT_APPROVED", False)),
                "app_id": _setting("LIVE_LAZADA_APP_KEY", "") or "",
                "redirect_uri": _setting("LIVE_LAZADA_REDIRECT_URI", "") or "",
                "auth_url": _setting("LIVE_LAZADA_AUTH_URL", SAFE_DEFAULTS["platforms"]["lazada"]["auth_url"]),
                "api_host": _setting("LIVE_LAZADA_API_HOST", SAFE_DEFAULTS["platforms"]["lazada"]["api_host"]),
                "token_path": _setting("LIVE_LAZADA_TOKEN_PATH", SAFE_DEFAULTS["platforms"]["lazada"]["token_path"]),
                "refresh_path": _setting("LIVE_LAZADA_REFRESH_PATH", SAFE_DEFAULTS["platforms"]["lazada"]["refresh_path"]),
                "market": _setting("LIVE_LAZADA_MARKET", "") or "",
            },
            "shopee": {
                "contract_approved": bool(_setting("LIVE_SHOPEE_CONTRACT_APPROVED", False)),
                "app_id": _setting("LIVE_SHOPEE_PARTNER_ID", "") or "",
                "redirect_uri": _setting("LIVE_SHOPEE_REDIRECT_URI", "") or "",
                "auth_url": _setting("LIVE_SHOPEE_AUTH_URL", SAFE_DEFAULTS["platforms"]["shopee"]["auth_url"]),
                "api_host": _setting("LIVE_SHOPEE_DEFAULT_HOST", SAFE_DEFAULTS["platforms"]["shopee"]["api_host"]),
                "token_path": _setting("LIVE_SHOPEE_TOKEN_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["token_path"]),
                "refresh_path": _setting("LIVE_SHOPEE_REFRESH_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["refresh_path"]),
                "revoke_path": _setting("LIVE_SHOPEE_REVOKE_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["revoke_path"]),
                "shop_path": _setting("LIVE_SHOPEE_SHOP_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["shop_path"]),
                "order_list_path": _setting("LIVE_SHOPEE_ORDER_LIST_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["order_list_path"]),
                "order_detail_path": _setting("LIVE_SHOPEE_ORDER_DETAIL_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["order_detail_path"]),
                "return_list_path": _setting("LIVE_SHOPEE_RETURN_LIST_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["return_list_path"]),
                "return_detail_path": _setting("LIVE_SHOPEE_RETURN_DETAIL_PATH", SAFE_DEFAULTS["platforms"]["shopee"]["return_detail_path"]),
                "market": _setting("LIVE_SHOPEE_MARKET", "") or "",
                "region": _setting("LIVE_SHOPEE_DEFAULT_REGION", "") or "",
            },
            "tiktok": {
                "contract_approved": bool(_setting("LIVE_TIKTOK_CONTRACT_APPROVED", False)),
                "app_id": _setting("LIVE_TIKTOK_APP_KEY", "") or "",
                "service_id": _setting("LIVE_TIKTOK_SERVICE_ID", "") or "",
                "redirect_uri": _setting("LIVE_TIKTOK_REDIRECT_URI", "") or "",
                "market": str(_setting("LIVE_TIKTOK_MARKET", "ROW") or "ROW").upper(),
                "auth_url": _configured_or_empty(_setting("LIVE_TIKTOK_DEFAULT_AUTH_URL", "")),
                "api_host": _configured_or_empty(_setting("LIVE_TIKTOK_DEFAULT_OPEN_HOST", "")),
                "auth_urls": {
                    str(market).upper(): _configured_or_empty(endpoint)
                    for market, endpoint in auth_urls.items()
                    if _configured_or_empty(endpoint)
                },
                "api_hosts": {
                    str(market).upper(): _configured_or_empty(endpoint)
                    for market, endpoint in api_hosts.items()
                    if _configured_or_empty(endpoint)
                },
                "token_host": _setting("LIVE_TIKTOK_TOKEN_HOST", SAFE_DEFAULTS["platforms"]["tiktok"]["token_host"]),
                "token_path": _setting("LIVE_TIKTOK_TOKEN_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["token_path"]),
                "refresh_path": _setting("LIVE_TIKTOK_REFRESH_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["refresh_path"]),
                "revoke_path": _configured_or_empty(_setting("LIVE_TIKTOK_REVOKE_PATH", "")),
                "authorized_shops_path": _setting("LIVE_TIKTOK_AUTHORIZED_SHOPS_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["authorized_shops_path"]),
                "metadata_path": _setting("LIVE_TIKTOK_METADATA_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["metadata_path"]),
                "order_list_path": _setting("LIVE_TIKTOK_ORDER_LIST_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["order_list_path"]),
                "order_detail_path": _setting("LIVE_TIKTOK_ORDER_DETAIL_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["order_detail_path"]),
                "return_list_path": _setting("LIVE_TIKTOK_RETURN_LIST_PATH", SAFE_DEFAULTS["platforms"]["tiktok"]["return_list_path"]),
            },
        },
    }
    if configured_modules:
        enabled = {str(item).strip().lower() for item in configured_modules if str(item).strip()}
        payload["modules"] = {code: ("enabled" if code in enabled else "disabled") for code in MODULE_CODES}
    return payload


def get_effective_runtime_version():
    """Return the current system-scope effective version, if the table exists."""
    try:
        from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion

        return (
            TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
            .filter(
                config_key=CONFIG_KEY,
                scope_key="system",
                status=TenantConfigVersion.Status.EFFECTIVE,
                definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
                effective_at__lte=timezone.now(),
            )
            .order_by("-version", "-id")
            .first()
        )
    # pytest-django (and a few management/health-check contexts) can install
    # a database blocker even though Django itself is configured.  Runtime
    # configuration must fail closed to safe defaults in that situation just
    # as it does when the config-center table has not been migrated yet.
    except (DatabaseError, OperationalError, ProgrammingError, RuntimeError):
        return None


def _load_snapshot():
    source = "default"
    validation_error = ""
    try:
        env_value = validate_runtime_config(_environment_config())
        resolved = _deep_merge(SAFE_DEFAULTS, env_value)
        source = "environment" if env_value != SAFE_DEFAULTS else "default"
    except ValidationError as exc:
        resolved = deepcopy(SAFE_DEFAULTS)
        source = "invalid_environment"
        validation_error = str(exc)

    version = get_effective_runtime_version()
    if version is not None:
        try:
            db_value = validate_runtime_config(version.value)
            resolved = _deep_merge(resolved, db_value)
            resolved = validate_runtime_config(resolved)
            source = "database"
            validation_error = ""
        except ValidationError as exc:
            # Never allow an invalid approved row to inherit an enabling env
            # value.  The safe default leaves all live gates closed.
            resolved = deepcopy(SAFE_DEFAULTS)
            source = "invalid_database"
            validation_error = str(exc)
    try:
        resolved = validate_runtime_config(resolved)
    except ValidationError as exc:
        resolved = deepcopy(SAFE_DEFAULTS)
        source = "invalid_runtime"
        validation_error = str(exc)
    return resolved, source, version, validation_error


def runtime_snapshot():
    resolved, source, version, validation_error = _load_snapshot()
    custody = resolved.get("custody", {})
    token_path = str(custody.get("auth_file_path") or "")
    token_available = False
    if token_path:
        try:
            token_available = Path(token_path).is_file()
        except OSError:
            token_available = False
    # Legacy env token is intentionally not returned; it is only a fallback
    # for old deployments that have not moved to a mounted auth file yet.
    if not token_available:
        token_available = bool(
            _setting("LIVE_CUSTODY_SERVICE_TOKEN", "")
            or _setting("LIVE_CUSTODY_SERVICE_AUTH_TOKEN", "")
        )
    return {
        "config_key": CONFIG_KEY,
        "config": deepcopy(resolved),
        "source": source,
        "valid": not source.startswith("invalid_"),
        "validation_error": validation_error,
        "effective_version": version.version if version is not None and source == "database" else None,
        "version_id": version.id if version is not None and source == "database" else None,
        "masked_status": {
            "credentials_stored": False,
            "custody": {
                "backend": custody.get("backend", "refuse"),
                "service_url_configured": bool(custody.get("service_url")),
                "service_host_configured": bool(custody.get("service_host")),
                "auth_file_path_configured": bool(token_path),
                "ca_file_path_configured": bool(custody.get("ca_file_path")),
                "token_available": token_available,
            },
        },
    }


def get_production_runtime_config():
    return runtime_snapshot()["config"]


def get_runtime_setting(*path, default=None):
    value = get_production_runtime_config()
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def get_runtime_platform_config(platform: str):
    """Return one platform's resolved non-secret settings for adapters."""
    platform = str(platform or "").strip().lower()
    config = deepcopy(get_runtime_setting("platforms", platform, default={}) or {})
    if platform not in _PLATFORM_KEYS:
        return config
    # Public IDs remain usable as environment fallbacks.  Never include raw
    # app secrets here; tenant config/custody resolves those at call time.
    setting_map = {
        "lazada": {"app_id": "LIVE_LAZADA_APP_KEY"},
        "shopee": {"app_id": "LIVE_SHOPEE_PARTNER_ID"},
        "tiktok": {"app_id": "LIVE_TIKTOK_APP_KEY", "service_id": "LIVE_TIKTOK_SERVICE_ID"},
    }
    for key, setting_name in setting_map.get(platform, {}).items():
        if not config.get(key):
            config[key] = _setting(setting_name, "") or ""
    if platform == "tiktok":
        market = str(config.get("market") or "ROW").upper()
        config["market"] = market
        config["auth_url"] = (config.get("auth_urls") or {}).get(market) or config.get("auth_url") or ""
        config["api_host"] = (config.get("api_hosts") or {}).get(market) or config.get("api_host") or ""
    return config


def get_listing_write_policy(config: dict | None = None):
    """Return the resolved, non-secret global-listing write policy.

    ``listing_write`` is intentionally independent from the integration
    synchronisation ``write_enabled`` flags.  This helper is useful to queue
    workers and readiness views that need to show the policy without deciding
    whether a particular production operation is safe.
    """
    if config is None:
        config = get_production_runtime_config()
    validated = validate_runtime_config(config)
    resolved = _deep_merge(SAFE_DEFAULTS, validated)
    return deepcopy(resolved["listing_write"])


def assert_listing_production_allowed(
    *,
    platform: str,
    action: str,
    store_id: int,
    batch_size: int = 1,
    confirm_production: bool = False,
    config: dict | None = None,
):
    """Assert that one global-listing production batch may enter the queue.

    This is a policy assertion only: it authorizes a *controlled internal
    queue envelope*.  It never calls a marketplace API.  Every rejection is a
    :class:`~django.core.exceptions.ValidationError` so HTTP callers and
    asynchronous workers fail closed in the same way.
    """
    # The coarse module switch is independent from the finer-grained listing
    # policy below, so disabling 全球刊登 also blocks queue admission.
    from apps.common.module_gate import is_module_enabled

    if not is_module_enabled("global_listing"):
        _raise("modules.global_listing", "global listing module is disabled")
    if confirm_production is not True:
        _raise("confirm_production", "production publication requires explicit confirmation")
    if config is None:
        snapshot = runtime_snapshot()
        if not snapshot.get("valid", False):
            _raise("listing_write", "effective production runtime configuration is invalid")
        resolved = snapshot["config"]
    else:
        try:
            resolved = _deep_merge(SAFE_DEFAULTS, validate_runtime_config(config))
            resolved = validate_runtime_config(resolved)
        except ValidationError:
            # Preserve the domain validator's field-level reason while making
            # it impossible for callers to continue after malformed policy.
            raise

    policy = get_listing_write_policy(resolved)
    normalized_platform = str(platform or "").strip().lower()
    normalized_action = str(action or "").strip().lower()
    if policy["mode"] != "controlled":
        _raise("listing_write.mode", "controlled listing production mode is not enabled")
    if policy["emergency_stop"] is not False:
        _raise("listing_write.emergency_stop", "listing production is blocked by the emergency stop")
    if policy["require_batch_approval"] is not True:
        _raise("listing_write.require_batch_approval", "each production batch requires approval")
    if normalized_platform not in LISTING_WRITE_PLATFORMS:
        _raise("platform", "unsupported production listing platform")
    if normalized_action not in LISTING_WRITE_ACTIONS:
        _raise("action", "production listing action is not allowed; delete is prohibited")
    if isinstance(store_id, bool) or not isinstance(store_id, int) or store_id <= 0:
        _raise("store_id", "production listing store_id must be a positive integer")
    if store_id not in policy["allowed_store_ids"]:
        _raise("store_id", "store is not in the approved production listing store allowlist")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        _raise("batch_size", "production listing batch_size must be a positive integer")
    if batch_size > policy["max_batch_size"]:
        _raise("batch_size", f"production listing batch exceeds max_batch_size ({policy['max_batch_size']})")
    if normalized_platform not in policy["allowed_platforms"]:
        _raise("platform", "platform is not in the approved production listing platform allowlist")
    if normalized_action not in policy["allowed_actions"]:
        _raise("action", "action is not in the approved production listing action allowlist")

    network = resolved.get("network", {})
    if network.get("mode") != LIVE_NETWORK_MODE:
        _raise("network.mode", "production listing requires the approved live-test network mode")
    if network.get("security_approved") is not True:
        _raise("network.security_approved", "production listing requires network security approval")
    if not network.get("allowed_hosts"):
        _raise("network.allowed_hosts", "production listing requires a non-empty outbound host allowlist")
    if _setting("DEBUG", False):
        _raise("network", "production listing is forbidden while DEBUG is enabled")

    platform_config = (resolved.get("platforms") or {}).get(normalized_platform) or {}
    if platform_config.get("contract_approved") is not True:
        _raise(f"platforms.{normalized_platform}.contract_approved", "platform contract approval is required")

    custody = resolved.get("custody") or {}
    if str(custody.get("backend") or "").strip().lower() == "refuse":
        _raise("custody.backend", "production listing requires a non-refusing credential custody backend")
    try:
        from .capability import approved_custody_configured

        custody_ready = approved_custody_configured()
    except Exception:
        custody_ready = False
    if not custody_ready:
        _raise("custody", "credential custody service is not approved for production listing")

    return {
        "platform": normalized_platform,
        "action": normalized_action,
        "store_id": store_id,
        "batch_size": batch_size,
        "execution_mode": "production",
        "external_platform_call": False,
        "policy": policy,
    }


# Compatibility aliases used by integration modules and tests.
get_runtime_config = get_production_runtime_config
get_runtime_snapshot = runtime_snapshot
