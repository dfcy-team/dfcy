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
