import json
import os

import pytest
from django.test import override_settings

from apps.integrations.capability import approved_custody_configured, live_mode_allowed
from apps.integrations.custody import CustodyError, HttpCustodyBackend, get_custody_backend, reset_custody_backend_cache
from apps.integrations import net_guard
from apps.integrations.net_guard import assert_host_allowed
from apps.integrations.oauth_errors import OAuthFlowError


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


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode checks are not available on Windows")
def test_http_custody_reads_owner_only_token_file_and_fails_closed_on_unsafe_file(tmp_path):
    token_file = tmp_path / "custody.token"
    token_file.write_text("file-token", encoding="utf-8")
    os.chmod(token_file, 0o400)
    client = _Client()
    with override_settings(
        LIVE_CUSTODY_SERVICE_TOKEN="",
        LIVE_CUSTODY_SERVICE_AUTH_TOKEN="",
        LIVE_CUSTODY_SERVICE_TOKEN_FILE=str(token_file),
    ):
        HttpCustodyBackend("https://custody.example.test", client).retrieve_secret("cred_1")
    assert client.calls[0]["headers"] == {"Authorization": "Bearer file-token"}

    os.chmod(token_file, 0o644)
    with override_settings(
        LIVE_CUSTODY_SERVICE_TOKEN="",
        LIVE_CUSTODY_SERVICE_AUTH_TOKEN="",
        LIVE_CUSTODY_SERVICE_TOKEN_FILE=str(token_file),
    ):
        with pytest.raises(CustodyError, match="permissions are unsafe"):
            HttpCustodyBackend("https://custody.example.test", _Client())


def test_non_standard_port_is_allowed_only_for_exact_custody_endpoint():
    with override_settings(
        LIVE_PLATFORM_ALLOWED_HOSTS=["platform.example.test"],
        LIVE_CUSTODY_SERVICE_URL="https://custody.example.test:8443",
        LIVE_CUSTODY_SERVICE_HOST="custody.example.test",
    ):
        assert_host_allowed("https://custody.example.test:8443/tokens") is None
        with pytest.raises(OAuthFlowError, match="Non-standard outbound ports"):
            assert_host_allowed("https://platform.example.test:8443/api")
        with pytest.raises(OAuthFlowError, match="Non-standard outbound ports"):
            assert_host_allowed("https://other.example.test:8443/api")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode checks are not available on Windows")
def test_private_custody_ca_is_loaded_only_for_exact_custody_endpoint(tmp_path, monkeypatch):
    ca_file = tmp_path / "custody-ca.pem"
    ca_file.write_text("not-used-by-fake-context", encoding="utf-8")
    os.chmod(ca_file, 0o400)

    class FakeContext:
        def __init__(self):
            self.loaded = []

        def load_verify_locations(self, *, cafile):
            self.loaded.append(cafile)

    context = FakeContext()

    class FakeResponse:
        status = 200

        def read(self, _limit):
            return b"{}"

        def getheaders(self):
            return []

    class FakeConnection:
        contexts = []

        def __init__(self, _host, _port, *, timeout, context):
            self.contexts.append(context)
            self.sock = None

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr(net_guard.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(net_guard.http.client, "HTTPSConnection", FakeConnection)
    with override_settings(
        LIVE_CUSTODY_SERVICE_URL="https://custody.example.test:8443",
        LIVE_CUSTODY_CA_FILE=str(ca_file),
    ):
        net_guard._default_transport("GET", "https://custody.example.test:8443/healthz")
        assert context.loaded == [str(ca_file)]
        context.loaded.clear()
        net_guard._default_transport("GET", "https://platform.example.test/api")
        assert context.loaded == []
