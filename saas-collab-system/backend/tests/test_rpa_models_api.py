import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.rpa.models import BigSellerAccount, RPAAgent, RPATask, RPATaskStepLog, RPATool
from apps.tenants.models import Tenant


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
@pytest.mark.parametrize(
    ("path", "action"),
    [
        ("/api/rpa/tasks/claim/", "claim"),
        ("/api/rpa/tasks/1/heartbeat/", "heartbeat"),
        ("/api/rpa/tasks/1/logs/", "logs"),
        ("/api/rpa/tasks/1/complete/", "complete"),
        ("/api/rpa/tasks/1/fail/", "fail"),
    ],
)
def test_rpa_placeholder_api_requires_rpa_user_and_returns_placeholder(path, action):
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = CustomUser.objects.create_user(
        username=f"rpa-{action}",
        tenant=tenant,
        user_type=CustomUser.UserType.RPA,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(path, data={}, format="json")

    assert response.status_code == 200
    assert response.json()["action"] == action


@pytest.mark.django_db
def test_rpa_placeholder_api_rejects_anonymous_user():
    response = APIClient().post("/api/rpa/tasks/claim/", data={}, format="json")

    assert response.status_code in {401, 403}
