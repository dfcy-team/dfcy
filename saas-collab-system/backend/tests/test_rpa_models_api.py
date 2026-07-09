import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.rpa.models import BigSellerAccount, RPAAgent, RPATask, RPATaskStepLog, RPATool
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
    )


@pytest.mark.django_db
def test_rpa_task_can_be_created_with_weak_business_reference():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_screenshot",
        business_type="purchase_order",
        business_id="PO-10001",
        payload={"url": "https://example.test/order/PO-10001"},
    )

    assert task.id is not None
    assert task.status == RPATask.Status.PENDING
    assert task.business_type == "purchase_order"
    assert task.business_id == "PO-10001"
    assert task.retry_count == 0
    assert task.max_retry_count == 3


@pytest.mark.django_db
def test_rpa_agent_tool_bigseller_account_and_step_log_can_be_created():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    tool = RPATool.objects.create(tenant=tenant, name="BigSeller Browser", code="bigseller-browser")
    agent = RPAAgent.objects.create(
        tenant=tenant,
        name="Desktop Agent",
        token_hash="sha256-placeholder",
        device_fingerprint="device-001",
        ip_whitelist=["127.0.0.1"],
    )
    account = BigSellerAccount.objects.create(
        tenant=tenant,
        name="Main BigSeller",
        account_identifier="main-bigseller",
        credential_ref="secret-manager-ref-only",
    )
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_login_check",
        business_type="bigseller_account",
        business_id=str(account.id),
        claimed_by=agent,
    )
    log = RPATaskStepLog.objects.create(
        tenant=tenant,
        task=task,
        step_name="open_page",
        status=RPATaskStepLog.Status.SUCCESS,
        message="Opened BigSeller page.",
    )

    assert tool.status == RPATool.Status.ACTIVE
    assert agent.status == RPAAgent.Status.ACTIVE
    assert account.status == BigSellerAccount.Status.ACTIVE
    assert log.task == task


@pytest.mark.django_db
def test_rpa_task_status_enum_contains_required_values():
    expected = {
        "pending",
        "claimed",
        "running",
        "success",
        "failed",
        "retrying",
        "manual_required",
        "cancelled",
    }

    assert expected == {choice[0] for choice in RPATask.Status.choices}


@pytest.mark.django_db
def test_rpa_task_has_no_direct_product_or_finance_foreign_keys():
    relation_targets = {
        field.remote_field.model._meta.label_lower
        for field in RPATask._meta.fields
        if getattr(field, "remote_field", None) and field.remote_field
    }

    assert "products.product" not in relation_targets
    assert not any(target.startswith("finance.") for target in relation_targets)


@pytest.mark.django_db
def test_rpa_agent_can_claim_pending_task():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-claim", CustomUser.UserType.RPA)
    agent = RPAAgent.objects.create(tenant=tenant, user=user, name="Agent", token_hash="hash")
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_price_check",
        business_type="listing",
        business_id="LISTING-1",
        payload={"queue_key": "bigseller"},
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post("/api/rpa/tasks/claim/", data={"queue_key": "bigseller"}, format="json")

    assert response.status_code == 200
    data = response.json()["data"]
    assert response.json()["success"] is True
    assert data["task_id"] == task.id
    assert data["status"] == RPATask.Status.CLAIMED
    task.refresh_from_db()
    assert task.status == RPATask.Status.CLAIMED
    assert task.claimed_by == agent
    assert task.claimed_at is not None


@pytest.mark.django_db
def test_rpa_claim_returns_empty_when_no_pending_task():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-empty", CustomUser.UserType.RPA)
    RPAAgent.objects.create(tenant=tenant, user=user, name="Agent", token_hash="hash")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post("/api/rpa/tasks/claim/", data={}, format="json")

    assert response.status_code == 200
    assert response.json()["data"] == {"task": None, "status": "empty"}


@pytest.mark.django_db
def test_rpa_agent_can_post_heartbeat_logs_screenshots_complete_and_fail():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-actions", CustomUser.UserType.RPA)
    agent = RPAAgent.objects.create(tenant=tenant, user=user, name="Agent", token_hash="hash")
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_page_check",
        business_type="listing",
        business_id="LISTING-2",
        status=RPATask.Status.CLAIMED,
        claimed_by=agent,
        payload={"page": "placeholder"},
    )
    client = APIClient()
    client.force_authenticate(user=user)

    heartbeat = client.post(
        f"/api/rpa/tasks/{task.id}/heartbeat/",
        data={"current_step": "open_page", "progress": 10},
        format="json",
    )
    log = client.post(
        f"/api/rpa/tasks/{task.id}/logs/",
        data={"step_name": "open_page", "status": "success", "message": "opened"},
        format="json",
    )
    screenshot = client.post(
        f"/api/rpa/tasks/{task.id}/screenshots/",
        data={
            "step_name": "open_page",
            "screenshot_ref": "local-placeholder-ref",
            "message": "placeholder only",
        },
        format="json",
    )
    complete = client.post(
        f"/api/rpa/tasks/{task.id}/complete/",
        data={
            "message": "done",
            "result": {"matched": True},
            "screenshots": ["local-placeholder-ref"],
            "page_url": "https://example.test/placeholder",
            "page_snapshot": {"title": "placeholder"},
        },
        format="json",
    )

    assert heartbeat.status_code == 200
    assert heartbeat.json()["data"]["status"] == RPATask.Status.RUNNING
    assert log.status_code == 200
    assert log.json()["data"]["log_id"]
    assert screenshot.status_code == 200
    assert screenshot.json()["data"]["screenshot_id"]
    assert complete.status_code == 200
    assert complete.json()["data"]["status"] == RPATask.Status.SUCCESS
    task.refresh_from_db()
    assert task.status == RPATask.Status.SUCCESS
    assert task.result["result"] == {"matched": True}
    assert RPATaskStepLog.objects.filter(task=task).count() == 2

    failed_task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_login_check",
        business_type="bigseller_account",
        business_id="ACCOUNT-1",
        status=RPATask.Status.RUNNING,
        claimed_by=agent,
    )
    fail = client.post(
        f"/api/rpa/tasks/{failed_task.id}/fail/",
        data={
            "message": "captcha required",
            "error_code": "CAPTCHA_REQUIRED",
            "error_message": "captcha required",
            "manual_required": True,
            "manual_reason": "captcha",
            "failed_step": "login",
            "last_success_step": "open_login_page",
        },
        format="json",
    )

    assert fail.status_code == 200
    assert fail.json()["data"]["status"] == RPATask.Status.MANUAL_REQUIRED
    failed_task.refresh_from_db()
    assert failed_task.status == RPATask.Status.MANUAL_REQUIRED
    assert failed_task.result["manual_required"] is True
    assert failed_task.result["manual_reason"] == "captcha"
    assert failed_task.result["failed_step"] == "login"
    assert failed_task.result["last_success_step"] == "open_login_page"


@pytest.mark.django_db
def test_rpa_user_without_bound_agent_cannot_claim_task():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-no-agent", CustomUser.UserType.RPA)
    RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_check",
        business_type="listing",
        business_id="LISTING-NO-AGENT",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post("/api/rpa/tasks/claim/", data={}, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
def test_rpa_agent_cannot_operate_task_claimed_by_another_agent():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user_a = create_user(tenant, "rpa-agent-a", CustomUser.UserType.RPA)
    user_b = create_user(tenant, "rpa-agent-b", CustomUser.UserType.RPA)
    agent_a = RPAAgent.objects.create(tenant=tenant, user=user_a, name="Agent A", token_hash="hash-a")
    RPAAgent.objects.create(tenant=tenant, user=user_b, name="Agent B", token_hash="hash-b")
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_check",
        business_type="listing",
        business_id="LISTING-OTHER-AGENT",
        status=RPATask.Status.RUNNING,
        claimed_by=agent_a,
    )
    client = APIClient()
    client.force_authenticate(user=user_b)

    response = client.post(f"/api/rpa/tasks/{task.id}/complete/", data={"result": {"ok": True}}, format="json")

    assert response.status_code == 403
    task.refresh_from_db()
    assert task.status == RPATask.Status.RUNNING
    assert task.result == {}


@pytest.mark.django_db
def test_rpa_screenshots_reject_external_urls_in_phase1():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-screenshot-url", CustomUser.UserType.RPA)
    agent = RPAAgent.objects.create(tenant=tenant, user=user, name="Agent", token_hash="hash")
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_check",
        business_type="listing",
        business_id="LISTING-SCREENSHOT",
        status=RPATask.Status.RUNNING,
        claimed_by=agent,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"/api/rpa/tasks/{task.id}/screenshots/",
        data={"screenshot_url": "https://example.test/screenshot.png"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    task.refresh_from_db()
    assert task.screenshot_url == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("user_type", "username"),
    [
        (CustomUser.UserType.INTERNAL, "internal-rpa-denied"),
        (CustomUser.UserType.EXTERNAL, "external-rpa-denied"),
    ],
)
def test_non_rpa_users_cannot_access_rpa_execution_interfaces(user_type, username):
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, username, user_type)
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="bigseller_check",
        business_type="listing",
        business_id="LISTING-3",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    paths = [
        "/api/rpa/tasks/claim/",
        f"/api/rpa/tasks/{task.id}/heartbeat/",
        f"/api/rpa/tasks/{task.id}/logs/",
        f"/api/rpa/tasks/{task.id}/screenshots/",
        f"/api/rpa/tasks/{task.id}/complete/",
        f"/api/rpa/tasks/{task.id}/fail/",
    ]

    for path in paths:
        response = client.post(path, data={}, format="json")
        assert response.status_code == 403


@pytest.mark.django_db
def test_rpa_execution_interfaces_reject_anonymous_user():
    paths = [
        "/api/rpa/tasks/claim/",
        "/api/rpa/tasks/1/heartbeat/",
        "/api/rpa/tasks/1/logs/",
        "/api/rpa/tasks/1/screenshots/",
        "/api/rpa/tasks/1/complete/",
        "/api/rpa/tasks/1/fail/",
    ]

    for path in paths:
        response = APIClient().post(path, data={}, format="json")
        assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_rpa_user_cannot_access_finance_api():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "rpa-finance-denied", CustomUser.UserType.RPA)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/finance/health/")

    assert response.status_code == 403
