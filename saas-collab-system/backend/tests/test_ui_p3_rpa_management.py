import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.rpa.models import RPAAgent, RPATask, RPATaskAttempt
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=user_type,
    )


def grant(user, *codes, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"role-{user.username}", name=user.username)
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "rpa", "action": code.split(".", 1)[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def create_device(tenant, name="dry-device", execution_mode=RPAAgent.ExecutionMode.DRY_RUN, user=None):
    return RPAAgent.objects.create(
        tenant=tenant,
        user=user,
        name=name,
        token_hash="not-a-real-token-hash",
        device_fingerprint="demo-device-fingerprint-001",
        execution_mode=execution_mode,
    )


def create_task(tenant, status=RPATask.Status.PENDING, **kwargs):
    defaults = {
        "task_type": "DEMO_DRY_RUN",
        "business_type": "demo",
        "business_id": "demo-business",
        "status": status,
        "payload": {"platform": "mock", "account_alias": "demo-account", "token": "not-a-real-token"},
    }
    defaults.update(kwargs)
    return RPATask.objects.create(tenant=tenant, **defaults)


def test_internal_task_and_run_queries_are_tenant_filtered_and_paginated():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p3-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p3-b")
    viewer = create_user(tenant, "rpa-viewer")
    grant(viewer, "rpa.tasks.view")
    device = create_device(tenant)
    task = create_task(tenant)
    hidden = create_task(other)
    RPATaskAttempt.objects.create(tenant=tenant, task=task, agent=device, attempt_no=1, started_at=task.created_at)

    tasks = client_for(viewer).get("/api/internal/rpa/tasks/?page=1&page_size=10")
    runs = client_for(viewer).get("/api/internal/rpa/runs/")

    assert tasks.status_code == 200
    assert tasks.data["data"]["count"] == 1
    assert tasks.data["data"]["results"][0]["id"] == task.id
    assert hidden.id not in {item["id"] for item in tasks.data["data"]["results"]}
    assert runs.status_code == 200
    assert runs.data["data"]["results"][0]["task_id"] == task.id


def test_custom_scope_limits_tasks_and_runs_to_declared_ids():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-custom")
    viewer = create_user(tenant, "custom-rpa-viewer")
    visible = create_task(tenant, business_id="visible")
    create_task(tenant, business_id="hidden")
    grant(
        viewer,
        "rpa.tasks.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"rpa_task_ids": [visible.id]},
    )

    response = client_for(viewer).get("/api/internal/rpa/tasks/")

    assert response.status_code == 200
    assert [item["id"] for item in response.data["data"]["results"]] == [visible.id]


def test_run_custom_scope_intersects_task_and_device_dimensions():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-run-intersection")
    viewer = create_user(tenant, "run-intersection-viewer")
    allowed_task = create_task(tenant, business_id="allowed-task")
    hidden_task = create_task(tenant, business_id="hidden-task")
    allowed_device = create_device(tenant, name="allowed-device")
    hidden_device = create_device(tenant, name="hidden-device")
    grant(
        viewer,
        "rpa.tasks.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={
            "rpa_task_ids": [allowed_task.id],
            "rpa_device_ids": [allowed_device.id],
        },
    )
    allowed = RPATaskAttempt.objects.create(
        tenant=tenant,
        task=allowed_task,
        agent=allowed_device,
        attempt_no=1,
        started_at=allowed_task.created_at,
    )
    RPATaskAttempt.objects.create(
        tenant=tenant,
        task=allowed_task,
        agent=hidden_device,
        attempt_no=2,
        started_at=allowed_task.created_at,
    )
    RPATaskAttempt.objects.create(
        tenant=tenant,
        task=hidden_task,
        agent=allowed_device,
        attempt_no=1,
        started_at=hidden_task.created_at,
    )

    response = client_for(viewer).get("/api/internal/rpa/runs/")

    assert response.status_code == 200
    assert [item["id"] for item in response.data["data"]["results"]] == [allowed.id]


def test_run_custom_scopes_are_unioned_between_authorized_roles():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-run-role-union")
    viewer = create_user(tenant, "run-role-union-viewer")
    permission = Permission.objects.get(code="rpa.tasks.view")
    visible_runs = []
    for index in range(2):
        task = create_task(tenant, business_id=f"role-task-{index}")
        device = create_device(tenant, name=f"role-device-{index}")
        role = Role.objects.create(tenant=tenant, code=f"run-role-{index}", name=f"Run role {index}")
        role.permissions.add(permission)
        UserRole.objects.create(tenant=tenant, user=viewer, role=role)
        DataScope.objects.create(
            tenant=tenant,
            role=role,
            scope_type=DataScope.ScopeType.CUSTOM,
            config={"rpa_task_ids": [task.id], "rpa_device_ids": [device.id]},
        )
        visible_runs.append(
            RPATaskAttempt.objects.create(
                tenant=tenant,
                task=task,
                agent=device,
                attempt_no=1,
                started_at=task.created_at,
            )
        )
    hidden_task = create_task(tenant, business_id="cross-role-combination")
    RPATaskAttempt.objects.create(
        tenant=tenant,
        task=hidden_task,
        agent=visible_runs[0].agent,
        attempt_no=1,
        started_at=hidden_task.created_at,
    )

    response = client_for(viewer).get("/api/internal/rpa/runs/")

    assert response.status_code == 200
    assert {item["id"] for item in response.data["data"]["results"]} == {
        run.id for run in visible_runs
    }


@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_internal_rpa_management_rejects_external_and_agent_users(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"ui-p3-{user_type}")
    user = create_user(tenant, f"blocked-{user_type}", user_type)
    grant(user, "rpa.tasks.view")
    assert client_for(user).get("/api/internal/rpa/tasks/").status_code == 403


def test_view_permission_cannot_assign_or_retry_manual_tasks():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-view-only")
    viewer = create_user(tenant, "rpa-view-only")
    grant(viewer, "rpa.tasks.view")
    task = create_task(tenant, RPATask.Status.MANUAL_REQUIRED)
    client = client_for(viewer)

    assert client.get("/api/internal/rpa/manual-queue/").status_code == 200
    assert client.post(f"/api/internal/rpa/tasks/{task.id}/assign-manual/", {}, format="json").status_code == 403
    assert client.post(f"/api/internal/rpa/tasks/{task.id}/retry-mock/", {}, format="json").status_code == 403


def test_manual_assignment_and_mock_retry_are_audited_without_execution():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-manual")
    manager = create_user(tenant, "rpa-manager")
    grant(manager, "rpa.tasks.view", "rpa.tasks.manage")
    task = create_task(tenant, RPATask.Status.MANUAL_REQUIRED)
    client = client_for(manager)

    assigned = client.post(
        f"/api/internal/rpa/tasks/{task.id}/assign-manual/",
        {"reason": "Review demo page change."},
        format="json",
    )
    retried = client.post(f"/api/internal/rpa/tasks/{task.id}/retry-mock/", {}, format="json")

    task.refresh_from_db()
    assert assigned.status_code == 200
    assert assigned.data["data"]["manual_assignee"] == manager.username
    assert retried.status_code == 200
    assert task.status == RPATask.Status.RETRYING
    assert task.claimed_by_id is None
    assert OperationLog.objects.filter(tenant=tenant, action="task.assign_manual", object_id=str(task.id)).exists()
    assert OperationLog.objects.filter(tenant=tenant, action="task.retry_mock", object_id=str(task.id)).exists()
    assert RPATaskAttempt.objects.count() == 0


def test_retry_mock_returns_409_for_illegal_state_and_422_at_retry_limit():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-retry-rules")
    manager = create_user(tenant, "retry-manager")
    grant(manager, "rpa.tasks.manage")
    pending = create_task(tenant, RPATask.Status.PENDING)
    exhausted = create_task(tenant, RPATask.Status.FAILED, retry_count=3, max_retry_count=3)
    client = client_for(manager)

    conflict = client.post(f"/api/internal/rpa/tasks/{pending.id}/retry-mock/", {}, format="json")
    invalid = client.post(f"/api/internal/rpa/tasks/{exhausted.id}/retry-mock/", {}, format="json")

    assert conflict.status_code == 409
    assert conflict.data["code"] == "STATE_CONFLICT"
    assert invalid.status_code == 422
    assert invalid.data["code"] == "BUSINESS_RULE_VIOLATION"


def test_device_list_masks_secrets_and_dry_run_never_connects_platform():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-device")
    operator = create_user(tenant, "device-operator")
    device_user = create_user(tenant, "dry-agent", CustomUser.UserType.RPA)
    grant(operator, "rpa.devices.view", "rpa.devices.dry_run")
    device = create_device(tenant, user=device_user)
    client = client_for(operator)

    listed = client.get("/api/internal/rpa/devices/")
    checked = client.post(f"/api/internal/rpa/devices/{device.id}/dry-run/", {}, format="json")

    row = listed.data["data"]["results"][0]
    assert listed.status_code == 200
    assert "token_hash" not in row and "ip_whitelist" not in row and "device_fingerprint" not in row
    assert row["fingerprint_masked"].startswith("demo")
    assert checked.status_code == 200
    assert checked.data["data"]["checks"]["platform_connection"] == "not_attempted"
    assert checked.data["data"]["checks"]["browser_automation"] == "not_attempted"
    assert OperationLog.objects.filter(action="device.dry_run", object_id=str(device.id)).exists()


def test_production_disabled_device_cannot_dry_run_or_claim_agent_task():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-production-disabled")
    operator = create_user(tenant, "production-operator")
    agent_user = create_user(tenant, "production-agent", CustomUser.UserType.RPA)
    grant(operator, "rpa.devices.dry_run")
    device = create_device(
        tenant,
        execution_mode=RPAAgent.ExecutionMode.PRODUCTION_DISABLED,
        user=agent_user,
    )
    create_task(tenant)

    dry_run = client_for(operator).post(f"/api/internal/rpa/devices/{device.id}/dry-run/", {}, format="json")
    claim = client_for(agent_user).post("/api/rpa/tasks/claim/", {}, format="json")

    assert dry_run.status_code == 422
    assert claim.status_code == 403


def test_task_detail_sanitizes_payload_and_exposes_separate_task_run_states():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p3-detail")
    viewer = create_user(tenant, "detail-viewer")
    grant(viewer, "rpa.tasks.view")
    device = create_device(tenant)
    task = create_task(tenant, RPATask.Status.RUNNING, claimed_by=device)
    run = RPATaskAttempt.objects.create(
        tenant=tenant,
        task=task,
        agent=device,
        attempt_no=1,
        started_at=task.created_at,
        status=RPATaskAttempt.Status.CLAIMED,
    )
    client = client_for(viewer)

    task_response = client.get(f"/api/internal/rpa/tasks/{task.id}/")
    run_response = client.get(f"/api/internal/rpa/runs/{run.id}/")

    assert task_response.data["data"]["status"] == RPATask.Status.RUNNING
    assert task_response.data["data"]["payload"]["token"] == "***"
    assert run_response.data["data"]["status"] == RPATaskAttempt.Status.CLAIMED
