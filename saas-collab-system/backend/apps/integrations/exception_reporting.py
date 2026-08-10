"""Django exception-report redaction for marketplace OAuth callbacks."""

from __future__ import annotations

import re
from collections.abc import Mapping

from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter


REDACTED = "********************"
CALLBACK_PATH = re.compile(
    r"^/api/internal/integrations/store-authorizations/oauth/callback/(?:shopee|tiktok)/?$"
)
SENSITIVE_NAME = re.compile(
    r"(?:code|state|sign|signature|token|secret|authorization|cookie|session|query|params|request)",
    re.IGNORECASE,
)


def _django_request(request):
    return getattr(request, "_request", request)


def is_marketplace_oauth_callback(request):
    request = _django_request(request)
    path = str(getattr(request, "path", "") or "") if request is not None else ""
    return bool(CALLBACK_PATH.fullmatch(path))


def _redact_multivalue_dict(values):
    if values is None:
        return
    mutable = getattr(values, "_mutable", None)
    try:
        if mutable is not None:
            values._mutable = True
        for key in list(values.keys()):
            if hasattr(values, "setlist"):
                values.setlist(key, [REDACTED])
            else:
                values[key] = REDACTED
    finally:
        if mutable is not None:
            values._mutable = mutable


def redact_callback_request(request):
    """Remove callback values from the request object retained by reporters."""
    request = _django_request(request)
    if not is_marketplace_oauth_callback(request):
        return
    _redact_multivalue_dict(getattr(request, "GET", None))
    for key in list(getattr(request, "COOKIES", {})):
        request.COOKIES[key] = REDACTED
    meta = getattr(request, "META", {})
    for key in list(meta):
        if key != "QUERY_STRING" and (
            key in {"HTTP_AUTHORIZATION", "HTTP_COOKIE"} or SENSITIVE_NAME.search(str(key))
        ):
            meta[key] = REDACTED
    meta["QUERY_STRING"] = ""


def _redact_value(name, value):
    if SENSITIVE_NAME.search(str(name)):
        return REDACTED
    if isinstance(value, Mapping):
        return {key: _redact_value(key, item) for key, item in value.items()}
    return value


class MarketplaceOAuthExceptionReporterFilter(SafeExceptionReporterFilter):
    """Redact callback fields even when an exception occurs before the view."""

    def get_safe_request_meta(self, request):
        values = super().get_safe_request_meta(request)
        if is_marketplace_oauth_callback(request):
            return {key: _redact_value(key, value) for key, value in values.items()}
        return values

    def get_safe_cookies(self, request):
        values = super().get_safe_cookies(request)
        if is_marketplace_oauth_callback(request):
            return {key: REDACTED for key in values}
        return values

    def get_post_parameters(self, request):
        values = super().get_post_parameters(request)
        if is_marketplace_oauth_callback(request):
            values = values.copy()
            _redact_multivalue_dict(values)
        return values

    def get_traceback_frame_variables(self, request, tb_frame):
        values = super().get_traceback_frame_variables(request, tb_frame)
        if not is_marketplace_oauth_callback(request):
            return values
        return [(name, _redact_value(name, value)) for name, value in values]


class MarketplaceOAuthExceptionReporter(ExceptionReporter):
    """Ensure GET values and raw URI cannot bypass the reporter filter."""

    def get_traceback_data(self):
        if is_marketplace_oauth_callback(self.request):
            redact_callback_request(self.request)
        data = super().get_traceback_data()
        if is_marketplace_oauth_callback(self.request):
            data["request_GET_items"] = [(key, REDACTED) for key in self.request.GET]
            data["request_COOKIES_items"] = [(key, REDACTED) for key in self.request.COOKIES]
            data["request_insecure_uri"] = str(self.request.path)
        return data
