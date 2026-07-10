from apps.common.security import mask_sensitive_text


SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "api_secret",
    "access_token",
    "refresh_token",
    "token",
    "cookie",
    "session",
    "password",
    "secret",
}

SENSITIVE_TEXT_MARKERS = (
    "not-a-real-secret",
    "placeholder-secret",
    "placeholder-token",
    "demo-secret",
)


def mask_secret(value):
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}***{text[-4:]}"


def sanitize_payload(payload):
    if isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    sanitized = {}
    for key, value in payload.items():
        key_text = str(key).lower()
        if any(sensitive in key_text for sensitive in SENSITIVE_KEYS):
            sanitized[key] = "***"
        else:
            sanitized[key] = sanitize_payload(value)
    return sanitized


def sanitize_text(value):
    text = str(value or "")
    for marker in SENSITIVE_TEXT_MARKERS:
        text = text.replace(marker, "***")
    return mask_sensitive_text(text)
