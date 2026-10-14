from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.integrations import feishu_binding as binding, feishu_login as login
from apps.integrations.models import FeishuBindingSession, FeishuConnection, FeishuIdentity, FeishuLoginSession
from apps.tenants.models import Tenant


BASE = "/api/feishu/login/bind/"
PASSWORD = "synthetic-test-password"


@pytest.fixture(autouse=True)
def configured_binding():
    cache.clear()
    with override_settings(DEBUG=True, FEISHU_LOGIN_APP_ID="cli_binding",
                           FEISHU_LOGIN_REDIRECT_URI="http://testserver" + login.CALLBACK_PATH):
        yield


@pytest.fixture
def subject(db, monkeypatch):
    tenant = Tenant.objects.create(name="Synthetic binding", code="binding")
    user = CustomUser.objects.create_user(username="self-binding", password=PASSWORD,
                                          tenant=tenant, user_type="internal")
    connection = FeishuConnection.objects.create(
        tenant=tenant, app_id="cli_binding", enabled=True, app_secret_ref="synthetic-reference",
        created_by=user, updated_by=user,
    )
    client = APIClient()
    client.force_authenticate(user)
    provider = Mock(return_value="ou_self_binding")
    monkeypatch.setattr(login.FeishuOAuthClient, "get_open_id", provider)
    directory = Mock()
    directory.find_candidate_by_open_id.return_value = {"open_id": "ou_self_binding"}
    monkeypatch.setattr(binding, "FeishuIdentityService", Mock(return_value=directory))
    return user, connection, client, provider


def start(client):
    response = client.post(BASE + "start/", {"current_password": PASSWORD}, format="json")
    assert response.status_code == 200, response.json()
    return parse_qs(urlsplit(response.json()["data"]["authorize_url"]).query)["state"][0]


def callback(client, state):
    return client.get(login.CALLBACK_PATH, {"state": state, "code": "synthetic-code"})


def complete(client):
    return client.post(BASE + "complete/", {}, format="json")


@pytest.mark.django_db
def test_self_binding_then_password_free_login(subject):
    user, connection, client, provider = subject
    status = client.get(BASE + "status/")
    assert status.json()["data"] == {
        "enabled": True, "bound": False, "status": None, "bound_at": None, "username": user.username,
    }
    state = start(client)
    assert state.startswith("bind_")
    session = FeishuBindingSession.objects.get()
    assert session.state_digest != state
    assert session.credential_digest != user.password
    assert client.cookies[binding.BROWSER_COOKIE]["httponly"]
    assert client.cookies[binding.BROWSER_COOKIE]["path"] == login.COOKIE_PATH
    public_callback = APIClient()
    public_callback.cookies[binding.BROWSER_COOKIE] = client.cookies[binding.BROWSER_COOKIE].value
    client = public_callback
    returned = callback(client, state)
    assert returned["Location"] == "/?feishu_binding=complete"
    assert returned["Cache-Control"] == "no-store"
    assert returned["Referrer-Policy"] == "no-referrer"
    assert not FeishuIdentity.objects.exists(), "public callback must not create a binding"
    assert complete(client).status_code == 401
    client.force_authenticate(user)
    response = complete(client)
    assert response.status_code == 200
    assert response.json()["data"]["bound"] is True
    assert set(response.json()["data"]) == {"enabled", "bound", "status", "bound_at", "username"}
    identity = FeishuIdentity.objects.get()
    assert (identity.user_id, identity.tenant_id, identity.open_id) == (user.pk, user.tenant_id, "ou_self_binding")
    session.refresh_from_db()
    assert session.stage == "consumed" and session.open_id == ""
    assert complete(client).status_code == 400
    audit = OperationLog.objects.get(action="feishu_self_bind")
    assert audit.user_id == user.pk and audit.after_data == {"identity_id": identity.pk}
    assert "synthetic-code" not in str(audit.after_data) and "ou_self_binding" not in str(audit.after_data)
    assert not FeishuLoginSession.objects.exists()
    # The binding can now be used through the unchanged, anonymous login flow.
    anonymous = APIClient()
    response = anonymous.post("/api/feishu/login/start/", {}, format="json")
    login_state = parse_qs(urlsplit(response.json()["data"]["authorize_url"]).query)["state"][0]
    assert callback(anonymous, login_state)["Location"] == "/login?feishu=complete"
    tokens = anonymous.post("/api/feishu/login/complete/", {}, format="json").json()["data"]
    anonymous.credentials(HTTP_AUTHORIZATION="Bearer " + tokens["access"])
    assert anonymous.get("/api/internal/auth/me/").json()["data"]["user_id"] == user.pk
    assert provider.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("path,method", [("status/", "get"), ("start/", "post"), ("complete/", "post")])
def test_binding_requires_current_authentication(subject, path, method):
    client = APIClient()
    response = getattr(client, method)(BASE + path)
    assert response.status_code == 401
    assert not FeishuBindingSession.objects.exists() and not FeishuIdentity.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [{}, {"current_password": "wrong"}, {"current_password": None},
                                     {"current_password": PASSWORD, "system_user_id": 99}])
def test_password_proof_and_no_arbitrary_user_selection(subject, payload):
    client = subject[2]
    response = client.post(BASE + "start/", payload, format="json")
    assert response.status_code == 403
    assert not FeishuBindingSession.objects.exists()
    subject[3].assert_not_called()


@pytest.mark.django_db
def test_state_browser_and_handoff_are_independent_from_login(subject):
    user, connection, client, provider = subject
    client.cookies[login.BROWSER_COOKIE] = "existing-login-browser"
    client.cookies[login.HANDOFF_COOKIE] = "existing-login-handoff"
    state = start(client)
    other = APIClient()
    other.force_authenticate(user)
    assert callback(other, state)["Location"] == "/?feishu_binding_error=state_invalid"
    provider.assert_not_called()
    assert callback(client, state)["Location"] == "/?feishu_binding=complete"
    other.cookies[binding.HANDOFF_COOKIE] = client.cookies[binding.HANDOFF_COOKIE].value
    assert complete(other).json()["code"] == "state_invalid"
    assert complete(client).status_code == 200
    assert client.cookies[login.BROWSER_COOKIE].value == "existing-login-browser"
    assert client.cookies[login.HANDOFF_COOKIE].value == "existing-login-handoff"


@pytest.mark.django_db
def test_replayed_callback_and_new_qr_cannot_exchange_old_code(subject):
    client, provider = subject[2:]
    old_state = start(client)
    new_state = start(client)
    assert callback(client, old_state)["Location"] == "/?feishu_binding_error=state_invalid"
    # A failed callback clears this browser's binding cookies; keep a new start
    # for the successful path, like the UI's explicit retry.
    new_state = start(client)
    assert callback(client, new_state)["Location"] == "/?feishu_binding=complete"
    assert callback(client, new_state)["Location"] == "/?feishu_binding_error=state_invalid"
    provider.assert_called_once()


@pytest.mark.django_db
def test_account_switch_cannot_bind_to_second_user(subject):
    user, connection, client, provider = subject
    state = start(client)
    callback(client, state)
    other = CustomUser.objects.create_user(username="other-binding", password=PASSWORD, tenant=user.tenant,
                                           user_type="internal")
    client.force_authenticate(other)
    assert complete(client).json()["code"] == "state_invalid"
    assert not FeishuIdentity.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("stage", ["callback", "complete"])
@pytest.mark.parametrize("change", ["password", "disabled", "external", "tenant", "connection", "secret", "expiry", "lease"])
def test_recheck_actor_and_configuration(subject, stage, change):
    user, connection, client, provider = subject
    state = start(client)
    if stage == "complete":
        callback(client, state)
    if change == "password":
        user.set_password("changed-system-password")
        user.save()
    elif change == "disabled":
        user.is_active = False
        user.save()
    elif change == "external":
        user.user_type = "external"
        user.save()
    elif change == "tenant":
        user.tenant = Tenant.objects.create(name="Other", code="other")
        user.save()
    elif change == "connection":
        connection.enabled = False
        connection.save()
    elif change == "secret":
        connection.app_secret_ref = "changed-secret-reference"
        connection.save()
    elif change == "expiry":
        FeishuBindingSession.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        user.username = "SC-UAT-user"
        user.tenant.code = "SC-UAT-tenant"
        user.tenant.save()
        user.save()
    response = callback(client, state) if stage == "callback" else complete(client)
    assert ("feishu_binding_error=" in response["Location"]) if stage == "callback" else response.status_code == 400
    assert not FeishuIdentity.objects.exists()
    if stage == "callback":
        provider.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("existing", ["self_active", "self_disabled", "other", "other_disabled"])
def test_existing_bindings_are_never_replaced(subject, existing):
    user, connection, client, provider = subject
    state = start(client)
    callback(client, state)
    owner = user if existing.startswith("self") else CustomUser.objects.create_user(
        username="occupied", password=PASSWORD, tenant=user.tenant, user_type="internal")
    identity = FeishuIdentity.objects.create(tenant=user.tenant, user=owner, open_id="ou_self_binding",
                                             status="disabled" if existing.endswith("disabled") else "active")
    before = (identity.user_id, identity.open_id, identity.status)
    response = complete(client)
    assert response.status_code == 409
    assert response.json()["code"] == ("already_bound" if owner == user else "identity_in_use")
    identity.refresh_from_db()
    assert (identity.user_id, identity.open_id, identity.status) == before
    assert FeishuIdentity.objects.count() == 1
    assert not OperationLog.objects.filter(action="feishu_self_bind").exists()


@pytest.mark.django_db
def test_preexisting_binding_disables_start_even_if_inactive(subject):
    user, connection, client, provider = subject
    FeishuIdentity.objects.create(tenant=user.tenant, user=user, open_id="ou_existing", status="disabled")
    assert client.get(BASE + "status/").json()["data"]["status"] == "inactive"
    response = client.post(BASE + "start/", {"current_password": PASSWORD}, format="json")
    assert response.status_code == 409 and response.json()["code"] == "already_bound"
    assert not FeishuBindingSession.objects.exists()


@pytest.mark.django_db
def test_cross_tenant_subject_cannot_start(subject):
    user, connection, client, provider = subject
    other_tenant = Tenant.objects.create(name="Different", code="different")
    other = CustomUser.objects.create_user(username="cross-tenant", password=PASSWORD,
                                           tenant=other_tenant, user_type="internal")
    client.force_authenticate(other)
    assert client.get(BASE + "status/").json()["data"]["enabled"] is False
    assert client.post(BASE + "start/", {"current_password": PASSWORD}, format="json").status_code == 403
    assert not FeishuBindingSession.objects.exists()


@pytest.mark.django_db
def test_cross_origin_and_payload_injection_cannot_mutate(subject):
    user, connection, client, provider = subject
    assert client.post(BASE + "start/", {"current_password": PASSWORD}, format="json",
                       HTTP_ORIGIN="https://evil.example").status_code == 403
    state = start(client)
    callback(client, state)
    assert client.post(BASE + "complete/", {"system_user_id": 99}, format="json").status_code == 403
    assert client.post(BASE + "complete/", {}, format="json", HTTP_ORIGIN="null").status_code == 403
    assert complete(client).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("provider_result", ["not-an-open-id", None, "ou_" + "a" * 130])
def test_invalid_provider_identity_cannot_create_binding(subject, provider_result):
    client, provider = subject[2:]
    provider.return_value = provider_result
    assert callback(client, start(client))["Location"] == "/?feishu_binding_error=provider_error"
    assert not FeishuIdentity.objects.exists()


@pytest.mark.django_db
def test_organization_directory_rejection_cannot_bind(subject, monkeypatch):
    client = subject[2]
    verify = Mock(side_effect=ValidationError({"detail": "remote-body-must-not-appear"}))
    monkeypatch.setattr(binding, "FeishuIdentityService", Mock(return_value=Mock(find_candidate_by_open_id=verify)))
    response = callback(client, start(client))
    assert response["Location"] == "/?feishu_binding_error=provider_error"
    verify.assert_called_once_with(connection=subject[1], open_id="ou_self_binding")
    assert FeishuBindingSession.objects.get().stage == "processing"
    assert not FeishuIdentity.objects.exists()
    assert not client.cookies[binding.HANDOFF_COOKIE].value


@pytest.mark.django_db
def test_denial_provider_error_and_password_throttle(subject):
    client, provider = subject[2:]
    state = start(client)
    assert client.get(login.CALLBACK_PATH, {"state": state, "error": "secret-no-echo"})["Location"] == "/?feishu_binding_error=denied"
    provider.assert_not_called()
    provider.side_effect = ValueError("must-not-appear")
    response = callback(client, start(client))
    assert response["Location"] == "/?feishu_binding_error=provider_error"
    assert "must-not-appear" not in str(response.headers)
    for _ in range(4):
        response = client.post(BASE + "start/", {"current_password": "incorrect"}, format="json")
    assert response.status_code == 429
