"""Common redaction policy for integration audit details.

Audit details are operational metadata, not a credential transport.  The
same redaction function is used when writing new rows and when serializing
historical rows so a legacy or hand-created record cannot expose a secret
through a read endpoint.
"""

import re


_AUDIT_SENSITIVE_KEYS = {
    "apikey",
    "secret",
    "cookie",
    "session",
    "sessionid",
    "bearer",
    "bearertoken",
    "authorization",
    "authtoken",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
    "credentials",
    "credential",
    "credentialid",
    "tokenid",
    "clientsecret",
    "apisecret",
    "appsecret",
    "adssecret",
    "partnerkey",
    "signingsecret",
    "webhooksecret",
    "credentialciphertext",
    "authorizationcode",
    "privatekey",
    "secretkey",
    "accesskey",
    "password",
}

# Header names can be wrapped by a transport/request prefix or suffix after
# normalization.  These are explicit header aliases rather than a broad
# ``authorization``/``session`` prefix rule; audit state keys such as
# ``authorization_status`` and ``session_status`` must remain observable.
_AUDIT_SENSITIVE_HEADER_MARKERS = {
    "xapikey",
    "setcookie",
    "proxyauthorization",
}

# Application fields may carry an opaque prefix (for example
# ``raw_client_secret``).  Suffix matching is intentionally limited to
# credential markers, avoiding false positives such as ``token_refreshed``.
_AUDIT_SENSITIVE_KEY_SUFFIXES = {
    "apikey",
    "secret",
    "cookie",
    "session",
    "bearer",
    "authorization",
    "authtoken",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "token",
}


def _normalize_audit_key(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_audit_key(key):
    """Return whether a JSON key identifies a credential or secret header."""
    normalized = _normalize_audit_key(key)
    if normalized in _AUDIT_SENSITIVE_KEYS:
        return True
    if any(
        normalized == marker
        or normalized.startswith(marker)
        or normalized.endswith(marker)
        for marker in _AUDIT_SENSITIVE_HEADER_MARKERS
    ):
        return True
    return any(normalized.endswith(marker) for marker in _AUDIT_SENSITIVE_KEY_SUFFIXES)


def sanitize_audit_detail(value):
    """Return a recursively redacted copy without mutating the input."""
    if isinstance(value, dict):
        return {
            key: sanitize_audit_detail(item)
            for key, item in value.items()
            if not is_sensitive_audit_key(key)
        }
    if isinstance(value, list):
        return [sanitize_audit_detail(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_audit_detail(item) for item in value)
    return value
