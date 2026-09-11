"""Closed-schema OAuth diagnostics. Never serialize exceptions or wire payloads."""
import hashlib
import json
import logging
import re
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from .oauth_errors import OAuthFlowError, OAUTH_AUTH_REJECTED, OAUTH_PROVIDER_ERROR, OAUTH_DATABASE_FAILURE

logger = logging.getLogger(__name__)
STAGES = {"validate_callback", "read_developer_secret", "exchange_token", "save_token", "verify_store", "save_authorization"}
CATEGORIES = {
    "ip_allowlist_rejected",
    "authentication_rejected", "custody_authentication_rejected", "custody_failure",
    "timeout_uncertain", "network_uncertain", "service_uncertain", "tls_failure",
    "platform_error", "identity_rejected", "database_failure", "configuration_changed", "validation_rejected",
}
# Exact literals only; these are diagnostic labels, not a guess at credential validity.
PLATFORM_ERROR_CODES = {"shopee": frozenset({
    "error_auth", "error_sign", "error_param", "error_permission", "error_perm",
    "error_limit", "error_network", "error_server", "error_inner",
}), "tiktok": frozenset({
    # TikTok Shop common-errors and Partner Center token-refresh FAQ.
    "106001", "106013", "36004001", "36004004", "36009004",
})}


def callback_url_key(value):
    # Do not canonicalize hosts, ports, escapes, parameters or non-root paths.
    parsed = urlsplit(str(value))
    return (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, parsed.fragment)


def response_metadata(response, platform):
    result = {"http_status": response.status_code}
    try:
        data = response.json()
    except (ValueError, TypeError):
        return result
    if not isinstance(data, dict):
        return result
    code = data.get("error") or data.get("code")
    if code:
        if platform == "tiktok" and type(code) is int:
            code = str(code)
        result["platform_error_code"] = code if isinstance(code, str) and code in PLATFORM_ERROR_CODES.get(platform, ()) else "UNCLASSIFIED"
    message = data.get("message")
    if (platform == "shopee" and response.status_code == 403
            and isinstance(code, str) and re.search(r"(?<![a-z])ip(?![a-z])", code.lower())
            and isinstance(message, str) and re.search(r"\b(?:whitelist|allowlist)\b", message.lower())):
        # Keep the unknown wire error code unclassified. Only emit this fixed
        # category; never copy the message, IP address or any other wire text.
        result["category"] = "ip_allowlist_rejected"
    request_id = data.get("request_id")
    if isinstance(request_id, str) and request_id:
        result["request_id_mask"] = "req-" + hashlib.sha256(request_id.encode()).hexdigest()[:16]
    return result


@contextmanager
def oauth_stage(stage, *, operation=""):
    try:
        yield
    except Exception as original:
        exc = original if isinstance(original, OAuthFlowError) else OAuthFlowError(
            OAUTH_DATABASE_FAILURE if stage == "save_authorization" else OAUTH_PROVIDER_ERROR,
            "OAuth stage could not be completed.",
        )
        if operation and not getattr(exc, "operation", None):
            exc.operation = operation
        if (operation in {"get_authorized_shops", "get_seller_permissions"}
                and getattr(exc, "http_status", 0) >= 400 and not getattr(exc, "category", None)):
            exc.category = "platform_error"
        if not getattr(exc, "stage", None):
            exc.stage = stage
            if stage in {"read_developer_secret", "save_token"}:
                if exc.controlled_code == OAUTH_AUTH_REJECTED:
                    exc.category = "custody_authentication_rejected"
                elif getattr(exc, "category", None) not in {"timeout_uncertain", "network_uncertain", "service_uncertain", "tls_failure"}:
                    exc.category = "custody_failure"
            elif not getattr(exc, "category", None):
                exc.category = {
                    "save_authorization": "database_failure", "verify_store": "identity_rejected",
                    "validate_callback": "validation_rejected",
                }.get(stage, "authentication_rejected" if exc.controlled_code == OAUTH_AUTH_REJECTED else "platform_error")
        # Discard raw text and exception chaining at the diagnostics boundary.
        exc.detail = f"OAuth flow rejected: {exc.controlled_code}"
        raise exc from None


def failure_diagnostic(exc, session):
    diagnostic = {
        "diagnostic_id": uuid.uuid4().hex,
        "stage": getattr(exc, "stage", "") if getattr(exc, "stage", "") in STAGES else "validate_callback",
        "category": getattr(exc, "category", "") if getattr(exc, "category", "") in CATEGORIES else "validation_rejected",
        "platform": session.platform,
        "config_id": session.integration_config_id,
        "oauth_session_id": session.pk,
    }
    http_status = getattr(exc, "http_status", None)
    operation = getattr(exc, "operation", "")
    if session.platform == "tiktok" and operation in {"get_authorized_shops", "get_seller_permissions"}:
        diagnostic["operation"] = operation
    if isinstance(http_status, int) and 100 <= http_status <= 599:
        diagnostic["http_status"] = http_status
    code = getattr(exc, "platform_error_code", None)
    if code is not None:
        diagnostic["platform_error_code"] = code if code in PLATFORM_ERROR_CODES.get(session.platform, ()) else "UNCLASSIFIED"
    mask = getattr(exc, "request_id_mask", "")
    if isinstance(mask, str) and len(mask) == 20 and mask.startswith("req-") and all(c in "0123456789abcdef" for c in mask[4:]):
        diagnostic["request_id_mask"] = mask
    for field, allowed in {
        "identity_evidence": {"shop_id_missing", "shop_id_mismatch", "invalid_shop_response", "token_scope_mismatch", "invalid_token_scope"},
        "token_scope_evidence": {"contains_callback_shop", "does_not_contain_callback_shop", "not_provided", "invalid_shape"},
    }.items():
        value = getattr(exc, field, None)
        if isinstance(value, str) and value in allowed:
            diagnostic[field] = value
    exc.diagnostic = diagnostic
    logger.warning("oauth_failure %s", json.dumps(diagnostic, sort_keys=True))
    return diagnostic
