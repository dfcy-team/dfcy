from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.rpa.models import (
    RPAAccountLock,
    RPAAgent,
    RPAEvidence,
    RPAPageSignature,
    RPATask,
    RPATaskAttempt,
    RPATaskStepLog,
)
from apps.rpa.stability_services import (
    acquire_account_lock,
    mark_heartbeat_timeouts,
    release_expired_account_locks,
)
from apps.tenants.models import Tenant


def create_agent(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.RPA,
    )
    agent = RPAAgent.objects.create(
        tenant=tenant,
        user=user,
        name=f"Agent {username}",
        token_hash="demo-token-hash",
    )
    return user, agent


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_task(tenant, business_id, **kwargs):
    defaults = {
        "task_type": "mock_page_check",
        "business_type": "demo_listing",
        "business_id": business_id,
    }
    defaults.update(kwargs)
    return RPATask.objects.create(tenant=tenant, **defaults)


@pytest.mark.django_db
def test_claim_creates_attempt_and_same_account_is_serialized():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-lock")
    user_a, agent_a = create_agent(tenant, "rpa-lock-a")
    user_b, _agent_b = create_agent(tenant, "rpa-lock-b")
    payload = {
        "platform": "mock",
        "account_alias": "demo-account",
        "api_token": "not-a-real-secret",
    }
    first = create_task(tenant, "DEMO-1", payload=payload)
    second = create_task(tenant, "DEMO-2", payload=payload)

    first_response = client_for(user_a).post("/api/rpa/tasks/claim/", {}, format="json")
    blocked_response = client_for(user_b).post("/api/rpa/tasks/claim/", {}, format="json")

    assert first_response.json()["data"]["task_id"] == first.id
    assert first_response.json()["data"]["payload"]["api_token"] == "***"
    assert "not-a-real-secret" not in str(first_response.json())
    assert blocked_response.json()["data"] == {"task": None, "status": "empty"}
    attempt = RPATaskAttempt.objects.get(task=first)
    assert attempt.agent == agent_a
    assert attempt.attempt_no == 1
    assert RPAAccountLock.objects.filter(task=first, lock_status=RPAAccountLock.LockStatus.HELD).exists()
    second.refresh_from_db()
    assert second.status == RPATask.Status.PENDING


@pytest.mark.django_db
def test_expired_account_lock_is_released_and_tenant_isolated():
    tenant_a = Tenant.objects.create(name="Tenant A", code="rpa-lock-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="rpa-lock-b")
    task_a1 = create_task(
        tenant_a,
        "A-1",
        payload={"platform": "mock", "account_alias": "shared-demo-account"},
    )
    task_a2 = create_task(
        tenant_a,
        "A-2",
        payload={"platform": "mock", "account_alias": "shared-demo-account"},
    )
    task_b = create_task(
        tenant_b,
        "B-1",
        payload={"platform": "mock", "account_alias": "shared-demo-account"},
    )
    expired_lock = acquire_account_lock(task_a1, lease_seconds=1)
    expired_lock.expires_at = timezone.now() - timedelta(seconds=1)
    expired_lock.save(update_fields=["expires_at"])

    assert release_expired_account_locks() == 1
    replacement = acquire_account_lock(task_a2)
    other_tenant_lock = acquire_account_lock(task_b)

    expired_lock.refresh_from_db()
    assert expired_lock.lock_status == RPAAccountLock.LockStatus.EXPIRED
    assert replacement.tenant == tenant_a
    assert other_tenant_lock.tenant == tenant_b


@pytest.mark.django_db
def test_retry_limit_moves_task_to_manual_required():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-retry-limit")
    user, agent = create_agent(tenant, "rpa-retry")
    task = create_task(
        tenant,
        "RETRY-1",
        status=RPATask.Status.RUNNING,
        claimed_by=agent,
        max_retry_count=1,
    )
    client = client_for(user)

    first_fail = client.post(
        f"/api/rpa/tasks/{task.id}/fail/",
        {"status": "retrying", "error_message": "temporary demo failure"},
        format="json",
    )
    second_claim = client.post("/api/rpa/tasks/claim/", {}, format="json")
    client.post(f"/api/rpa/tasks/{task.id}/heartbeat/", {}, format="json")
    second_fail = client.post(
        f"/api/rpa/tasks/{task.id}/fail/",
        {"status": "retrying", "error_message": "still failing"},
        format="json",
    )

    task.refresh_from_db()
    assert first_fail.json()["data"]["status"] == RPATask.Status.RETRYING
    assert second_claim.json()["data"]["task_id"] == task.id
    assert second_fail.json()["data"]["status"] == RPATask.Status.MANUAL_REQUIRED
    assert task.retry_count == 1
    assert task.status == RPATask.Status.MANUAL_REQUIRED
    assert list(task.attempts.values_list("attempt_no", flat=True)) == [1, 2]


@pytest.mark.django_db
def test_heartbeat_timeout_requires_manual_intervention_without_retry():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-timeout")
    _user, agent = create_agent(tenant, "rpa-timeout")
    task = create_task(tenant, "TIMEOUT-1", status=RPATask.Status.RUNNING, claimed_by=agent)
    old_time = timezone.now() - timedelta(minutes=10)
    attempt = RPATaskAttempt.objects.create(
        tenant=tenant,
        task=task,
        attempt_no=1,
        agent=agent,
        started_at=old_time,
        heartbeat_at=old_time,
        status=RPATaskAttempt.Status.RUNNING,
    )

    changed = mark_heartbeat_timeouts(timeout_seconds=300)

    task.refresh_from_db()
    attempt.refresh_from_db()
    assert changed == 1
    assert task.status == RPATask.Status.MANUAL_REQUIRED
    assert task.retry_count == 0
    assert attempt.status == RPATaskAttempt.Status.MANUAL_REQUIRED
    assert attempt.manual_required is True


@pytest.mark.django_db
def test_page_signature_change_pauses_task_for_manual_review():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-signature")
    user, agent = create_agent(tenant, "rpa-signature")
    task = create_task(tenant, "SIGNATURE-1", status=RPATask.Status.CLAIMED, claimed_by=agent)
    client = client_for(user)

    baseline = client.post(
        f"/api/rpa/tasks/{task.id}/heartbeat/",
        {"platform": "mock", "page_type": "listing", "page_signature_hash": "demo-signature-v1"},
        format="json",
    )
    changed = client.post(
        f"/api/rpa/tasks/{task.id}/heartbeat/",
        {"platform": "mock", "page_type": "listing", "page_signature_hash": "demo-signature-v2"},
        format="json",
    )

    task.refresh_from_db()
    assert baseline.json()["data"]["continue_running"] is True
    assert changed.json()["data"]["continue_running"] is False
    assert changed.json()["data"]["status"] == RPATask.Status.MANUAL_REQUIRED
    assert task.status == RPATask.Status.MANUAL_REQUIRED
    assert RPAPageSignature.objects.filter(detected_status=RPAPageSignature.DetectedStatus.CHANGED).count() == 1


@pytest.mark.django_db
def test_manual_required_failure_records_masked_attempt_details():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-manual")
    user, agent = create_agent(tenant, "rpa-manual")
    task = create_task(tenant, "MANUAL-1", status=RPATask.Status.RUNNING, claimed_by=agent)
    client = client_for(user)

    log_response = client.post(
        f"/api/rpa/tasks/{task.id}/logs/",
        {
            "step_name": "demo_login",
            "status": "failed",
            "message": "token=not-a-real-secret password=demo-password",
        },
        format="json",
    )
    fail_response = client.post(
        f"/api/rpa/tasks/{task.id}/fail/",
        {
            "manual_required": True,
            "manual_reason": "demo captcha",
            "failed_step": "demo_login",
            "last_success_step": "open_demo_page",
            "error_message": "cookie=demo-cookie session=demo-session",
        },
        format="json",
    )

    task.refresh_from_db()
    log = RPATaskStepLog.objects.get(task=task)
    attempt = RPATaskAttempt.objects.get(task=task)
    stored_text = f"{log.message} {task.error_message} {task.result} {attempt.masked_error}"
    assert log_response.status_code == 200
    assert fail_response.json()["data"]["status"] == RPATask.Status.MANUAL_REQUIRED
    assert "not-a-real-secret" not in stored_text
    assert "demo-password" not in stored_text
    assert "demo-cookie" not in stored_text
    assert "demo-session" not in stored_text
    assert attempt.failed_step == "demo_login"
    assert attempt.last_success_step == "open_demo_page"


@pytest.mark.django_db
def test_screenshot_creates_placeholder_evidence_and_rejects_real_reference():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-evidence")
    user, agent = create_agent(tenant, "rpa-evidence")
    task = create_task(tenant, "EVIDENCE-1", status=RPATask.Status.RUNNING, claimed_by=agent)
    client = client_for(user)

    accepted = client.post(
        f"/api/rpa/tasks/{task.id}/screenshots/",
        {"screenshot_ref": "demo-screenshot-placeholder", "step_name": "demo_step"},
        format="json",
    )
    rejected = client.post(
        f"/api/rpa/tasks/{task.id}/screenshots/",
        {"screenshot_ref": "C:/real/screenshot.png"},
        format="json",
    )

    evidence = RPAEvidence.objects.get(task=task)
    assert accepted.status_code == 200
    assert evidence.placeholder_url == "demo-screenshot-placeholder"
    assert len(evidence.payload_hash) == 64
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_wrong_agent_cannot_complete_or_fail_task():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-owner")
    _owner_user, owner_agent = create_agent(tenant, "rpa-owner")
    other_user, _other_agent = create_agent(tenant, "rpa-other")
    task = create_task(tenant, "OWNER-1", status=RPATask.Status.RUNNING, claimed_by=owner_agent)
    client = client_for(other_user)

    complete = client.post(f"/api/rpa/tasks/{task.id}/complete/", {"result": {}}, format="json")
    fail = client.post(f"/api/rpa/tasks/{task.id}/fail/", {"message": "demo"}, format="json")

    task.refresh_from_db()
    assert complete.status_code == 403
    assert fail.status_code == 403
    assert task.status == RPATask.Status.RUNNING


@pytest.mark.django_db
def test_terminal_task_rejects_illegal_state_rollback():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-terminal")
    user, agent = create_agent(tenant, "rpa-terminal")
    task = create_task(tenant, "TERMINAL-1", status=RPATask.Status.SUCCESS, claimed_by=agent)
    client = client_for(user)

    heartbeat = client.post(f"/api/rpa/tasks/{task.id}/heartbeat/", {}, format="json")
    fail = client.post(
        f"/api/rpa/tasks/{task.id}/fail/",
        {"status": "retrying", "message": "demo rollback"},
        format="json",
    )

    task.refresh_from_db()
    assert heartbeat.status_code == 400
    assert fail.status_code == 400
    assert task.status == RPATask.Status.SUCCESS


@pytest.mark.django_db
def test_rpa_agent_cannot_access_internal_or_admin_surfaces():
    tenant = Tenant.objects.create(name="Tenant", code="rpa-boundary")
    user, _agent = create_agent(tenant, "rpa-boundary")
    client = client_for(user)

    internal_response = client.get("/api/internal/products/research/")
    admin_response = client.get("/admin/")

    assert internal_response.status_code == 403
    assert admin_response.status_code != 200
