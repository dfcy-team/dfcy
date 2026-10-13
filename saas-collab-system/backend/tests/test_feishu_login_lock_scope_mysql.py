"""Feishu login locks on isolated MySQL with DB_NAME=synthetic_feishu_login."""

import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.db import OperationalError, close_old_connections, connection, connections, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.integrations import feishu_login as login
from apps.integrations.models import FeishuConnection, FeishuIdentity, FeishuLoginSession
from apps.tenants.models import Tenant


BASE = "/api/feishu/login/"
MYSQL_TEST_DATABASE = "test_synthetic_feishu_login"
THREAD_DEADLINE_SECONDS = 8


@pytest.fixture(autouse=True)
def mysql_only_database():
    if connection.vendor != "mysql":
        pytest.skip("requires MySQL locking semantics")
    if connection.settings_dict["NAME"] != MYSQL_TEST_DATABASE:
        pytest.skip("refusing to run outside the synthetic Feishu test database")
    assert connection.settings_dict["HOST"] == "127.0.0.1"
    cache.clear()
    with override_settings(
        DEBUG=True,
        FEISHU_LOGIN_APP_ID="cli_login",
        FEISHU_LOGIN_REDIRECT_URI="http://testserver" + login.CALLBACK_PATH,
    ):
        yield


@pytest.fixture
def ready_handoff(db, monkeypatch):
    tenant = Tenant.objects.create(name="Synthetic Feishu", code="synthetic-feishu")
    user = CustomUser.objects.create_user(
        username="synthetic-feishu-user", password="test-password",
        tenant=tenant, user_type="internal",
    )
    configured = FeishuConnection.objects.create(
        tenant=tenant, app_id="cli_login", enabled=True,
        app_secret_ref="synthetic-reference", created_by=user, updated_by=user,
    )
    identity = FeishuIdentity.objects.create(tenant=tenant, user=user, open_id="ou_synthetic")
    monkeypatch.setattr(login.FeishuOAuthClient, "get_open_id", lambda self, conn, code: "ou_synthetic")

    client = APIClient()
    response = client.post(BASE + "start/", {}, format="json")
    assert response.status_code == 200
    state = parse_qs(urlsplit(response.json()["data"]["authorize_url"]).query)["state"][0]
    callback = client.get(BASE + "callback/", {"state": state, "code": "synthetic-code"})
    assert callback.status_code == 302
    assert callback["Location"] == "/login?feishu=complete"
    assert FeishuLoginSession.objects.get().stage == "ready"
    return tenant, user, configured, client


def _complete_in_thread(client, results, key, *, barrier=None):
    close_old_connections()
    started = time.monotonic()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")
        if barrier is not None:
            barrier.wait(timeout=THREAD_DEADLINE_SECONDS)
        response = client.post(BASE + "complete/", {}, format="json")
        results[key] = (response.status_code, time.monotonic() - started, None)
    except BaseException as exc:  # Return worker failures to the asserting thread.
        results[key] = (None, time.monotonic() - started, repr(exc))
    finally:
        connections.close_all()


def _run_and_join(threads):
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(THREAD_DEADLINE_SECONDS)
    assert all(not thread.is_alive() for thread in threads), "complete worker exceeded its deadline"


@pytest.mark.django_db(transaction=True)
def test_audit_foreign_key_shared_locks_do_not_block_completion(ready_handoff):
    tenant, user, _configured, client = ready_handoff
    # Keep the inserted audit row uncommitted. Its FK checks hold shared locks on
    # tenant/user rows; these are compatible with reads but conflict with the old
    # joined SELECT FOR UPDATE attempting to lock every selected table.
    with transaction.atomic():
        OperationLog.objects.create(
            tenant=tenant, user=user, module="accounts", action="ordinary",
            object_type="user", object_id=str(user.pk),
        )
        results = {}
        worker = threading.Thread(target=_complete_in_thread, args=(client, results, "complete"))
        _run_and_join([worker])

    status, elapsed, error = results["complete"]
    assert error is None, f"complete worker failed after {elapsed:.3f}s: {error}"
    assert status == 200, f"complete returned HTTP {status} after {elapsed:.3f}s"
    assert elapsed < 2, f"complete waited {elapsed:.3f}s despite only FK shared locks"
    assert FeishuLoginSession.objects.get().stage == "consumed"


@pytest.mark.django_db(transaction=True)
def test_same_handoff_can_complete_only_once_concurrently(ready_handoff):
    _tenant, user, _configured, original = ready_handoff
    clients = [APIClient(), APIClient()]
    for client in clients:
        client.cookies[login.BROWSER_COOKIE] = original.cookies[login.BROWSER_COOKIE].value
        client.cookies[login.HANDOFF_COOKIE] = original.cookies[login.HANDOFF_COOKIE].value

    barrier = threading.Barrier(2)
    results = {}
    threads = [
        threading.Thread(target=_complete_in_thread, args=(client, results, i), kwargs={"barrier": barrier})
        for i, client in enumerate(clients)
    ]
    _run_and_join(threads)

    outcomes = [results[i] for i in range(2)]
    assert all(error is None for _status, _elapsed, error in outcomes), outcomes
    assert sorted(status for status, _elapsed, _error in outcomes) == [200, 400], outcomes
    assert all(elapsed < THREAD_DEADLINE_SECONDS for _status, elapsed, _error in outcomes), outcomes
    assert FeishuLoginSession.objects.get().stage == "consumed"
    assert OperationLog.objects.filter(action="login", user=user).count() == 1


@pytest.mark.django_db(transaction=True)
def test_completion_holds_identity_lock_until_token_creation_finishes(ready_handoff, monkeypatch):
    _tenant, user, _configured, client = ready_handoff
    identity = FeishuIdentity.objects.get(user=user)
    token_creation_entered = threading.Event()
    release_token_creation = threading.Event()
    worker_result = {}
    real_get_token = login.InternalTokenObtainPairSerializer.get_token

    def pause_then_create_real_token(target_user):
        token_creation_entered.set()
        if not release_token_creation.wait(THREAD_DEADLINE_SECONDS - 1):
            raise TimeoutError("test did not release token creation before deadline")
        return real_get_token(target_user)

    monkeypatch.setattr(
        login.InternalTokenObtainPairSerializer, "get_token", staticmethod(pause_then_create_real_token)
    )
    worker = threading.Thread(target=_complete_in_thread, args=(client, worker_result, "complete"))
    previous_lock_timeout = None
    lock_error = None
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            previous_lock_timeout = cursor.fetchone()[0]
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 2")

        worker.start()
        assert token_creation_entered.wait(THREAD_DEADLINE_SECONDS), "complete never reached token creation"
        try:
            with transaction.atomic():
                identity.status = "disabled"
                identity.save(update_fields=["status"])
        except OperationalError as exc:
            lock_error = exc
    finally:
        release_token_creation.set()
        if worker.ident is not None:
            worker.join(THREAD_DEADLINE_SECONDS)
        if previous_lock_timeout is not None:
            with connections["default"].cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", [previous_lock_timeout])

    assert not worker.is_alive(), "complete worker did not finish after token creation was released"
    assert lock_error is not None, "identity update unexpectedly succeeded while complete was creating its token"
    assert lock_error.args and lock_error.args[0] == 1205, f"expected MySQL lock timeout 1205, got {lock_error!r}"
    status, elapsed, error = worker_result["complete"]
    assert error is None, f"complete worker failed after {elapsed:.3f}s: {error}"
    assert status == 200, f"complete returned HTTP {status} after {elapsed:.3f}s"
    identity.refresh_from_db()
    assert identity.status == "active"
    assert FeishuLoginSession.objects.get().stage == "consumed"
    assert OperationLog.objects.filter(action="login", user=user).count() == 1
