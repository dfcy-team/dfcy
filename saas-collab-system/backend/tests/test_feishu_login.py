from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.integrations import feishu_login as login
from apps.integrations.models import FeishuConnection, FeishuIdentity, FeishuLoginSession
from apps.integrations.net_guard import HttpResponse
from apps.integrations.oauth_errors import OAUTH_AUTH_REJECTED, OAuthFlowError
from apps.tenants.models import Tenant


BASE = "/api/feishu/login/"


@pytest.fixture(autouse=True)
def configure_login():
    cache.clear()
    with override_settings(DEBUG=True, FEISHU_LOGIN_APP_ID="cli_login",
                           FEISHU_LOGIN_REDIRECT_URI="http://testserver" + login.CALLBACK_PATH):
        yield


@pytest.fixture
def bound_user(db):
    tenant = Tenant.objects.create(name="Company", code="login")
    user = CustomUser.objects.create_user(username="bound", password="existing-password",
                                          tenant=tenant, user_type="internal")
    connection = FeishuConnection.objects.create(tenant=tenant, app_id="cli_login", enabled=True,
                                                  app_secret_ref="opaque-reference", created_by=user,
                                                  updated_by=user)
    identity = FeishuIdentity.objects.create(tenant=tenant, user=user, open_id="ou_bound")
    return user, connection, identity


def start(client):
    response = client.post(BASE + "start/", {}, format="json")
    assert response.status_code == 200
    query = parse_qs(urlsplit(response.json()["data"]["authorize_url"]).query)
    return query["state"][0]


def callback(client, state):
    return client.get(BASE + "callback/", {"state": state, "code": "one-use-feishu-code"})


@pytest.fixture
def provider(monkeypatch):
    get_open_id = Mock(return_value="ou_bound")
    monkeypatch.setattr(login.FeishuOAuthClient, "get_open_id", get_open_id)
    return get_open_id


@pytest.mark.django_db
def test_bound_user_receives_normal_tokens_once(bound_user, provider):
    client = APIClient()
    state = start(client)
    assert client.cookies[login.BROWSER_COOKIE]["httponly"]
    assert client.cookies[login.BROWSER_COOKIE]["samesite"] == "Lax"
    session = FeishuLoginSession.objects.get()
    assert session.state_digest != state
    assert session.browser_digest != client.cookies[login.BROWSER_COOKIE].value
    response = callback(client, state)
    assert response.status_code == 302
    assert response["Location"] == "/login?feishu=complete"
    assert response["Cache-Control"] == "no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    assert client.cookies[login.HANDOFF_COOKIE]["httponly"]
    response = client.post(BASE + "complete/", {}, format="json")
    assert response.status_code == 200
    tokens = response.json()["data"]
    assert set(tokens) == {"access", "refresh"}
    client.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access"])
    me = client.get("/api/internal/auth/me/")
    assert me.json()["data"]["user_id"] == bound_user[0].pk
    assert me.json()["data"]["tenant_id"] == bound_user[0].tenant_id
    assert client.post(BASE + "complete/", {}, format="json").status_code == 400
    assert FeishuLoginSession.objects.get().stage == "consumed"
    assert OperationLog.objects.filter(action="login", user=bound_user[0]).count() == 1
    assert "one-use-feishu-code" not in str(OperationLog.objects.get().after_data)
    provider.assert_called_once()


@pytest.mark.django_db
def test_unbound_identity_preserves_password_login(bound_user, provider):
    provider.return_value = "ou_unbound"
    client = APIClient()
    assert callback(client, start(client))["Location"] == "/login?feishu_error=unbound"
    assert not client.cookies.get(login.HANDOFF_COOKIE).value
    response = client.post("/api/internal/auth/login/", {
        "username": "bound", "password": "existing-password"}, format="json")
    assert response.status_code == 200
    assert CustomUser.objects.count() == 1
    assert FeishuIdentity.objects.count() == 1


@pytest.mark.django_db
def test_other_browser_and_replayed_state_cannot_exchange(bound_user, provider):
    client, attacker = APIClient(), APIClient()
    state = start(client)
    assert callback(attacker, state)["Location"] == "/login?feishu_error=state_invalid"
    provider.assert_not_called()
    assert callback(client, state)["Location"] == "/login?feishu=complete"
    assert callback(client, state)["Location"] == "/login?feishu_error=state_invalid"
    provider.assert_called_once()


@pytest.mark.django_db
def test_handoff_cookie_alone_cannot_complete(bound_user, provider):
    client = APIClient()
    callback(client, start(client))
    attacker = APIClient()
    attacker.cookies[login.HANDOFF_COOKIE] = client.cookies[login.HANDOFF_COOKIE].value
    assert attacker.post(BASE + "complete/", {}, format="json").json()["code"] == "state_invalid"
    assert client.post(BASE + "complete/", {}, format="json").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("phase", ["callback", "complete"])
def test_expiry_fails_closed(bound_user, provider, phase):
    client = APIClient()
    state = start(client)
    if phase == "complete":
        callback(client, state)
    FeishuLoginSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = callback(client, state) if phase == "callback" else client.post(BASE + "complete/", {}, format="json")
    assert ("expired" in response["Location"]) if phase == "callback" else response.json()["code"] == "expired"


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["disabled_user", "external_user", "tenant", "disabled_identity", "duplicate", "wrong_tenant", "lease"])
def test_unavailable_binding_cannot_login(bound_user, provider, change):
    user, connection, identity = bound_user
    client = APIClient()
    state = start(client)
    if change == "disabled_user":
        user.is_active = False
        user.save()
    elif change == "external_user":
        user.user_type = "external"
        user.save()
    elif change == "tenant":
        user.tenant.status = "suspended"
        user.tenant.save()
    elif change == "disabled_identity":
        identity.status = "disabled"
        identity.save()
    elif change == "duplicate":
        other = CustomUser.objects.create_user(username="duplicate", tenant=user.tenant, user_type="internal")
        FeishuIdentity.objects.create(tenant=user.tenant, user=other, open_id=identity.open_id)
    elif change == "wrong_tenant":
        user.tenant = Tenant.objects.create(name="Other", code="other")
        user.save()
    else:
        user.username = "SC-UAT-user"
        user.tenant.code = "SC-UAT-tenant"
        user.tenant.save()
        user.save()
    response = callback(client, state)
    assert response["Location"] in {"/login?feishu_error=account_unavailable", "/login?feishu_error=config_unavailable"}
    assert not client.cookies.get(login.HANDOFF_COOKIE).value


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["disable", "app_id", "secret", "unbind", "user", "rebind"])
def test_recheck_configuration_and_binding_at_completion(bound_user, provider, change):
    user, connection, identity = bound_user
    client = APIClient()
    callback(client, start(client))
    if change == "disable":
        connection.enabled = False
        connection.save()
    elif change == "app_id":
        connection.app_id = "other-app"
        connection.save()
    elif change == "secret":
        connection.app_secret_ref = "new-reference"
        connection.save()
    elif change == "unbind":
        identity.delete()
    elif change == "rebind":
        identity.user = CustomUser.objects.create_user(username="rebound", tenant=user.tenant, user_type="internal")
        identity.save()
    else:
        user.is_active = False
        user.save()
    assert client.post(BASE + "complete/", {}, format="json").status_code == 400


@pytest.mark.django_db
def test_configuration_requires_pinned_same_origin_and_single_tenant(bound_user):
    client = APIClient()
    assert client.get(BASE + "config/").json()["data"] == {"enabled": True}
    with override_settings(FEISHU_LOGIN_REDIRECT_URI="https://evil.example" + login.CALLBACK_PATH):
        assert client.get(BASE + "config/").json()["data"] == {"enabled": False}
    with override_settings(FEISHU_LOGIN_APP_ID=""):
        assert client.post(BASE + "start/", {}, format="json").status_code == 503
    tenant = Tenant.objects.create(name="Ambiguous", code="ambiguous")
    FeishuConnection.objects.create(tenant=tenant, app_id="cli_login", app_secret_ref="another-reference",
                                   enabled=True, created_by=bound_user[0], updated_by=bound_user[0])
    assert client.get(BASE + "config/").json()["data"] == {"enabled": False}


@pytest.mark.django_db
def test_cross_origin_start_and_complete_rejected(bound_user, provider):
    client = APIClient()
    assert client.post(BASE + "start/", {}, format="json", HTTP_ORIGIN="https://evil.example").status_code == 403
    callback(client, start(client))
    assert client.post(BASE + "complete/", {}, format="json", HTTP_ORIGIN="null").status_code == 403
    assert client.post(BASE + "complete/", {}, format="json").status_code == 200


@pytest.mark.django_db
def test_provider_failure_and_denial_never_echo_secrets(bound_user, provider):
    client = APIClient()
    provider.side_effect = OAuthFlowError(OAUTH_AUTH_REJECTED, "client_secret=must-never-appear")
    response = callback(client, start(client))
    assert response["Location"] == "/login?feishu_error=provider_error"
    assert "must-never-appear" not in str(response.headers)
    provider.reset_mock()
    state = start(client)
    response = client.get(BASE + "callback/", {"state": state, "error": "secret-from-provider"})
    assert response["Location"] == "/login?feishu_error=denied"
    provider.assert_not_called()


@pytest.mark.django_db
def test_oauth_client_uses_official_endpoints_without_retries(bound_user, monkeypatch):
    http = Mock()
    http.request.side_effect = [
        HttpResponse(200, {}, '{"code":0,"access_token":"temporary-provider-token"}'),
        HttpResponse(200, {}, '{"code":0,"data":{"open_id":"ou_bound"}}'),
    ]
    custody = Mock()
    custody.retrieve_secret.return_value = "secret-only-in-memory"
    monkeypatch.setattr(login, "PlatformHttpClient", Mock(return_value=http))
    monkeypatch.setattr(login, "get_custody_backend", Mock(return_value=custody))
    assert login.FeishuOAuthClient().get_open_id(bound_user[1], "auth-code") == "ou_bound"
    token_call, profile_call = http.request.call_args_list
    assert token_call.args == ("POST", "https://open.feishu.cn/open-apis/authen/v2/oauth/token")
    assert token_call.kwargs["json_body"]["client_secret"] == "secret-only-in-memory"
    assert "scope" not in token_call.kwargs["json_body"]
    assert token_call.kwargs["retry"] is False
    assert profile_call.args == ("GET", "https://open.feishu.cn/open-apis/authen/v1/user_info")
    assert profile_call.kwargs["headers"] == {"Authorization": "Bearer temporary-provider-token"}


@pytest.mark.django_db
@pytest.mark.parametrize("payload", ['{}', '{"error":"bad-secret"}', '{"access_token":123}', '[]', 'not-json'])
def test_malformed_provider_token_fails_closed(bound_user, monkeypatch, payload):
    client = login.FeishuOAuthClient()
    client.http = Mock()
    client.http.request.return_value = HttpResponse(200, {}, payload)
    custody = Mock()
    custody.retrieve_secret.return_value = "secret"
    monkeypatch.setattr(login, "get_custody_backend", Mock(return_value=custody))
    with pytest.raises((ValueError, TypeError)):
        client.get_open_id(bound_user[1], "auth-code")


@pytest.mark.django_db
def test_secure_cookie_and_throttling(bound_user):
    client = APIClient()
    with override_settings(FEISHU_LOGIN_REDIRECT_URI="https://testserver" + login.CALLBACK_PATH):
        response = client.post(BASE + "start/", {}, format="json", secure=True)
        assert response.cookies[login.BROWSER_COOKIE]["secure"]
    for _ in range(20):
        response = client.get(BASE + "config/")
    assert response.status_code == 429
