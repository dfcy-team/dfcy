import re


SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(password|passwd|token|api[_-]?key|api[_-]?secret|cookie|session)\s*[:=]\s*([^\s,;]+)"
)
SENSITIVE_KEYS = {
    "authorization",
    "password",
    "passwd",
    "token",
    "api_key",
    "api_secret",
    "secret",
    "cookie",
    "session",
}


def mask_sensitive_text(value):
    text = str(value or "")
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=***", text)


def sanitize_sensitive_data(value):
    if isinstance(value, list):
        return [sanitize_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if not isinstance(value, dict):
        return value

    sanitized = {}
    for key, item in value.items():
        normalized_key = str(key).lower().replace("-", "_")
        if any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_KEYS):
            sanitized[key] = "***"
        else:
            sanitized[key] = sanitize_sensitive_data(item)
    return sanitized
