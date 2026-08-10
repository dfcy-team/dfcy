import logging
import sys
import urllib.parse

import pytest
from django.conf import settings
from django.test import RequestFactory
from django.views.debug import get_exception_reporter_class
from rest_framework.request import Request

from apps.integrations import views as integration_views
from apps.integrations.exception_reporting import REDACTED
from apps.integrations.oauth_errors import OAUTH_DATABASE_FAILURE, OAuthFlowError


SHOPEE_CALLBACK_PATH = (
    "/api/internal/integrations/store-authorizations/oauth/callback/shopee/"
)
SENSITIVE_MARKERS = {
    "code": "sensitive-code-marker",
    "state": "sensitive-state-marker",
    "sign": "sensitive-sign-marker",
    "access_token": "sensitive-token-marker",
}


def _callback_request():
    request = RequestFactory().get(
        SHOPEE_CALLBACK_PATH,
        SENSITIVE_MARKERS,
        HTTP_AUTHORIZATION="Bearer sensitive-authorization-marker",
        HTTP_COOKIE="sessionid=sensitive-session-marker",
    )
    return request


def _assert_no_markers(value):
    text = str(value)
    for marker in (
        *SENSITIVE_MARKERS.values(),
        "sensitive-authorization-marker",
        "sensitive-session-marker",
    ):
        assert marker not in text


def test_default_exception_reporter_redacts_callback_get_headers_and_cookies():
    request = _callback_request()

    try:
        raise RuntimeError("synthetic unexpected callback failure")
    except RuntimeError:
        reporter_class = get_exception_reporter_class(request)
        report = reporter_class(request, *sys.exc_info()).get_traceback_text()

    assert settings.DEFAULT_EXCEPTION_REPORTER.endswith("MarketplaceOAuthExceptionReporter")
    assert settings.DEFAULT_EXCEPTION_REPORTER_FILTER.endswith(
        "MarketplaceOAuthExceptionReporterFilter"
    )
    assert reporter_class.__name__ == "MarketplaceOAuthExceptionReporter"
    assert SHOPEE_CALLBACK_PATH in report
    assert REDACTED in report
    _assert_no_markers(report)


def test_unexpected_live_callback_error_is_controlled_and_does_not_log_query(
    monkeypatch,
    caplog,
):
    django_request = _callback_request()
    request = Request(django_request)
    captured = {}

    def fail_with_non_oauth_error(**kwargs):
        captured["query_params"] = kwargs["query_params"]
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(integration_views, "live_network_mode_enabled", lambda: True)
    monkeypatch.setattr(
        integration_views,
        "get_live_callback_result_uri",
        lambda: "https://console.example.test/integrations/configs",
    )
    monkeypatch.setattr(
        integration_views,
        "complete_marketplace_oauth_callback",
        fail_with_non_oauth_error,
    )

    with caplog.at_level(logging.ERROR, logger="apps.integrations.views"):
        response = integration_views._marketplace_oauth_callback(request, "shopee")

    query = urllib.parse.parse_qs(urllib.parse.urlsplit(response["Location"]).query)
    assert response.status_code == 303
    assert query == {
        "oauth": ["error"],
        "platform": ["shopee"],
        "error_code": [OAUTH_DATABASE_FAILURE],
    }
    assert captured["query_params"] == {}
    assert set(django_request.GET.values()) == {REDACTED}
    assert django_request.META["QUERY_STRING"] == ""
    _assert_no_markers(response["Location"])
    _assert_no_markers(caplog.text)


def test_unexpected_synthetic_callback_error_is_controlled_and_request_is_redacted(
    monkeypatch,
    caplog,
):
    django_request = _callback_request()
    request = Request(django_request)

    monkeypatch.setattr(integration_views, "live_network_mode_enabled", lambda: False)

    def fail_with_non_oauth_error(**kwargs):
        raise RuntimeError("synthetic custody outage")

    monkeypatch.setattr(
        integration_views,
        "complete_marketplace_oauth_callback",
        fail_with_non_oauth_error,
    )

    with caplog.at_level(logging.ERROR, logger="apps.integrations.views"):
        with pytest.raises(OAuthFlowError) as exc:
            integration_views._marketplace_oauth_callback(request, "shopee")

    assert exc.value.controlled_code == OAUTH_DATABASE_FAILURE
    assert set(django_request.GET.values()) == {REDACTED}
    assert django_request.META["QUERY_STRING"] == ""
    _assert_no_markers(caplog.text)
