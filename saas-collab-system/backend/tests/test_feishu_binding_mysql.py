"""Actual competing binding writers on a disposable synthetic MySQL database."""

import threading
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations import feishu_binding as binding, feishu_login as login, feishu_api
from apps.integrations.models import FeishuBindingSession, FeishuConnection, FeishuIdentity
from apps.tenants.models import Tenant


@pytest.fixture(autouse=True)
def isolated_mysql():
    if connection.vendor != "mysql":
        pytest.skip("requires actual MySQL row locks")
    if connection.settings_dict["NAME"] != "test_synthetic_feishu_login":
        pytest.skip("refusing non-synthetic database")
    assert connection.settings_dict["HOST"] == "127.0.0.1"
    cache.clear()
    with override_settings(DEBUG=True, FEISHU_LOGIN_APP_ID="cli_binding",
                           FEISHU_LOGIN_REDIRECT_URI="http://testserver" + login.CALLBACK_PATH):
        yield


def ready_client(user):
    client = APIClient()
    client.force_authenticate(user)
    response = client.post("/api/feishu/login/bind/start/", {"current_password": "synthetic-password"}, format="json")
    assert response.status_code == 200
    state = parse_qs(urlsplit(response.json()["data"]["authorize_url"]).query)["state"][0]
    assert client.get(login.CALLBACK_PATH, {"state": state, "code": "synthetic-code"})["Location"] == "/?feishu_binding=complete"
    return client


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("second_writer", ["self", "administrator"])
def test_competing_bindings_leave_one_owner(monkeypatch, second_writer):
    tenant = Tenant.objects.create(name="Synthetic competition", code="binding-race")
    users = [CustomUser.objects.create_user(username=f"binding-{i}", password="synthetic-password",
                                             tenant=tenant, user_type="internal") for i in range(2)]
    FeishuConnection.objects.create(tenant=tenant, app_id="cli_binding", enabled=True,
                                    app_secret_ref="synthetic-reference", created_by=users[0], updated_by=users[0])
    monkeypatch.setattr(login.FeishuOAuthClient, "get_open_id", lambda *args: "ou_competing")
    verified = {"open_id": "ou_competing", "user_id": "", "union_id": "", "department_ids": []}
    directory = Mock(find_candidate_by_open_id=Mock(return_value=verified))
    monkeypatch.setattr(binding, "FeishuIdentityService", Mock(return_value=directory))
    monkeypatch.setattr(feishu_api, "FeishuIdentityService", Mock(return_value=directory))
    clients = [ready_client(users[0])]
    if second_writer == "self":
        clients.append(ready_client(users[1]))
    else:
        admin = CustomUser.objects.create_user(username="binding-admin", password="synthetic-password",
                                              tenant=tenant, user_type="internal", is_superuser=True)
        client = APIClient()
        client.force_authenticate(admin)
        clients.append(client)
    barrier = threading.Barrier(2)
    results = {}

    def run(index):
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")
            barrier.wait(timeout=8)
            if index == 1 and second_writer == "administrator":
                response = clients[index].put(
                    f"/api/internal/integrations/feishu/identities/system-users/{users[1].pk}/bind/",
                    {"open_id": "ou_competing"}, format="json")
            else:
                response = clients[index].post("/api/feishu/login/bind/complete/", {}, format="json")
            results[index] = (response.status_code, response.json().get("code"))
        except BaseException as exc:
            results[index] = (None, repr(exc))
        finally:
            connections.close_all()

    workers = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(8)
    assert all(not worker.is_alive() for worker in workers)
    assert set(results) == {0, 1}
    assert sum(status == 200 for status, _code in results.values()) == 1, results
    assert all(status in {200, 400, 409} for status, _code in results.values()), results
    assert FeishuIdentity.objects.filter(tenant=tenant, open_id="ou_competing").count() == 1
    assert FeishuIdentity.objects.count() == 1
    assert FeishuBindingSession.objects.filter(stage="consumed").count() <= 1
