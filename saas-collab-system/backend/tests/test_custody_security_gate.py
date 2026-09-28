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
    with override_settings(
        LIVE_CUSTODY_SERVICE_TOKEN="",
        LIVE_CUSTODY_SERVICE_AUTH_TOKEN="",
        LIVE_CUSTODY_SERVICE_TOKEN_FILE="",
        LIVE_CUSTODY_SERVICE_AUTH_TOKEN_FILE="",
    ):
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
        LIVE_CUSTODY_SERVICE_HOST="",
        LIVE_CUSTODY_SERVICE_TOKEN=token,
        LIVE_CUSTODY_SERVICE_TOKEN_FILE="",
        LIVE_CUSTODY_SERVICE_AUTH_TOKEN_FILE="",
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


def test_root_deployment_allowlist_is_not_hidden_by_database_runtime_snapshot(monkeypatch):
    def runtime_setting(*path, default=None):
        if path == ("network", "allowed_hosts"):
            return ["partner.shopeemobile.com"]
        return default

    monkeypatch.setattr(net_guard, "get_runtime_setting", runtime_setting)
    with override_settings(LIVE_PLATFORM_ALLOWED_HOSTS=["open.feishu.cn"]):
        assert net_guard.get_allowed_hosts() == {"open.feishu.cn", "partner.shopeemobile.com"}
        assert_host_allowed("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal") is None
        with pytest.raises(OAuthFlowError, match="Outbound host is not approved"):
            assert_host_allowed("https://unapproved.example.test/api")


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


@pytest.mark.parametrize("proxy_url,custody,expected_host,expected_tunnel", [
    ("http://127.0.0.1:7897", False, "127.0.0.1", ("platform.example.test", 443)),
    ("", False, "platform.example.test", None),
    ("http://127.0.0.1:7897", True, "platform.example.test", None),
])
def test_platform_transport_uses_only_explicit_loopback_https_proxy(
    monkeypatch, proxy_url, custody, expected_host, expected_tunnel,
):
    created = []

    class FakeResponse:
        status = 200

        def read(self, _limit):
            return b"{}"

        def getheaders(self):
            return []

    class FakeConnection:
        def __init__(self, host, port, *, timeout, context):
            self.host = host
            self.port = port
            self.tunnel = None
            self.sock = None
            created.append(self)

        def set_tunnel(self, host, port):
            self.tunnel = (host, port)

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr(net_guard.http.client, "HTTPSConnection", FakeConnection)
    monkeypatch.setattr(net_guard, "_is_configured_custody_destination", lambda parsed: custody)
    monkeypatch.setattr(net_guard, "_validated_custody_ca_file", lambda: None)
    with override_settings(LIVE_HTTPS_PROXY_URL=proxy_url):
        net_guard._default_transport("GET", "https://platform.example.test/api")
    assert created[0].host == expected_host
    assert created[0].port == (7897 if expected_tunnel else 443)
    assert created[0].tunnel == expected_tunnel


@pytest.mark.parametrize("proxy_url", [
    "http://proxy.example.test:7897", "http://127.0.0.1:0",
    "http://@127.0.0.1:7897", "http://demo:example@127.0.0.1:7897",
    "https://127.0.0.1:7897", "http://127.0.0.1:7897/path",
])
def test_platform_transport_rejects_unapproved_https_proxy(proxy_url):
    with override_settings(LIVE_HTTPS_PROXY_URL=proxy_url):
        with pytest.raises(OAuthFlowError, match="approved loopback endpoint"):
            net_guard._default_transport("GET", "https://platform.example.test/api")
