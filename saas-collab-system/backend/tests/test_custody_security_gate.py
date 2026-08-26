import json

import pytest
from django.test import override_settings

from apps.integrations.capability import approved_custody_configured, live_mode_allowed
from apps.integrations.custody import CustodyError, HttpCustodyBackend, get_custody_backend, reset_custody_backend_cache


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload=None):
        self.payload = payload or {"value": "resolved-value"}
        self.calls = []

    def request(self, method, url, *, json_body=None, headers=None):
        self.calls.append({"method": method, "url": url, "body": json_body, "headers": headers})
        return _Response(self.payload)


def test_http_custody_requires_authentication_and_sends_bearer_header():
    client = _Client()
    backend = HttpCustodyBackend("https://custody.example.test", client, service_auth_token="custody-token")

    assert backend.retrieve_secret("cred_1") == "resolved-value"
    assert client.calls[0]["headers"] == {"Authorization": "Bearer custody-token"}
    assert "custody-token" not in json.dumps(client.calls[0]["body"] or {})


def test_http_custody_rejects_missing_service_authentication():
    with override_settings(LIVE_CUSTODY_SERVICE_TOKEN="", LIVE_CUSTODY_SERVICE_AUTH_TOKEN=""):
        with pytest.raises(CustodyError, match="authentication is not configured"):
            HttpCustodyBackend("https://custody.example.test", _Client())


@pytest.mark.parametrize(
    "backend, debug, token, expected",
    [
        ("file", False, "", False),
        ("http", False, "", False),
        ("http", False, "service-token", True),
    ],
)
def test_only_authenticated_http_custody_can_satisfy_live_gate(backend, debug, token, expected, tmp_path):
    with override_settings(
        DEBUG=debug,
        LIVE_CUSTODY_BACKEND=backend,
        CREDENTIAL_CUSTODY_PATH=str(tmp_path),
        LIVE_CUSTODY_SERVICE_URL="https://custody.example.test",
        LIVE_CUSTODY_SERVICE_TOKEN=token,
        LIVE_PLATFORM_ALLOWED_HOSTS=["platform.example.test"],
        PLATFORM_NETWORK_MODE="approved-live-test",
        LIVE_PLATFORM_SECURITY_APPROVED=True,
    ):
        assert approved_custody_configured() is expected
        assert live_mode_allowed() is expected


def test_file_custody_is_rejected_outside_local_debug_mode(tmp_path):
    reset_custody_backend_cache()
    try:
        with override_settings(DEBUG=False, LIVE_CUSTODY_BACKEND="file", CREDENTIAL_CUSTODY_PATH=str(tmp_path)):
            with pytest.raises(CustodyError, match="local synthetic/test mode"):
                get_custody_backend()
    finally:
        reset_custody_backend_cache()
