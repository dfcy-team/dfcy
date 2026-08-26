import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.adapters import DisabledProductionAdapter, MockPlatformAdapter
from apps.integrations.models import (
    PlatformIntegrationConfig,
    SyncCursor,
    SyncJob,
    SyncRun,
    WebhookEvent,
    authorization_service_write,
)
from apps.integrations.sync_services import calculate_backoff_seconds, record_retry_failure, record_webhook_event
from apps.integrations.sync_services import run_sync_job
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant_integration_access(user):
    role = Role.objects.create(tenant=user.tenant, name="Tech Admin", code=f"tech-admin-{user.id}")
    for permission_code in ("integrations.view", "integrations.manage", "integrations.rotate", "integrations.run"):
        action = permission_code.rsplit(".", 1)[-1]
        permission, _created = Permission.objects.get_or_create(
            code=permission_code,
            defaults={
                "name": f"Integrations {action}",
                "module": "integrations",
                "action": action,
            },
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def grant_integration_view_only(user):
    role = Role.objects.create(tenant=user.tenant, name="Integration Viewer", code=f"integration-viewer-{user.id}")
    permission, _created = Permission.objects.get_or_create(
        code="integrations.view",
        defaults={"name": "View integrations", "module": "integrations", "action": "view"},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_config(tenant, user, environment=PlatformIntegrationConfig.Environment.MOCK, alias="demo-sync"):
    with authorization_service_write():
        return PlatformIntegrationConfig.objects.create(
            tenant=tenant,
            platform="mock",
            account_alias=alias,
            environment=environment,
            status=PlatformIntegrationConfig.Status.ACTIVE
            if environment != PlatformIntegrationConfig.Environment.PRODUCTION
            else PlatformIntegrationConfig.Status.PENDING_REVIEW,
            credential_key_version="test-v1",
            credential_fingerprint="placeholder-fingerprint",
            created_by=user,
        )


def create_sync_job(tenant, user, environment=PlatformIntegrationConfig.Environment.MOCK, alias="demo-sync"):
    config = create_config(tenant, user, environment=environment, alias=alias)
    return SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        resource_type=SyncJob.ResourceType.MOCK_RECORD,
        schedule_type=SyncJob.ScheduleType.MANUAL,
    )


@pytest.mark.django_db
def test_sync_job_api_uses_tenant_scope_and_standard_response():
    tenant = Tenant.objects.create(name="Tenant A", code="tenant-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user = create_user(tenant, "tech-a")
    other_user = create_user(other_tenant, "tech-b")
    grant_integration_access(user)
    grant_integration_access(other_user)
    config = create_config(tenant, user)

    response = authenticated_client(user).post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "resource_type": "mock_record",
            "schedule_type": "manual",
            "max_retry_count": 3,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["success"] is True
    assert response.json()["code"] == "OK"
    assert response.json()["data"]["tenant_id"] == tenant.id

    other_response = authenticated_client(other_user).get("/api/internal/integrations/sync-jobs/")
    assert other_response.status_code == 200
    assert other_response.json()["data"] == []


@pytest.mark.django_db
def test_integration_workspace_links_tenant_scoped_config_jobs_and_runs():
    tenant = Tenant.objects.create(name="Tenant A", code="workspace-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="workspace-b")
    user = create_user(tenant, "workspace-user")
    other_user = create_user(other_tenant, "workspace-other")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    grant_integration_access(user)
    grant_integration_access(other_user)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="tenant-a-config",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    other_config = PlatformIntegrationConfig.objects.create(
        tenant=other_tenant,
        platform="mock",
        account_alias="tenant-b-config",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=other_user,
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type=SyncJob.ResourceType.MOCK_RECORD)
    SyncJob.objects.create(tenant=other_tenant, integration_config=other_config, resource_type=SyncJob.ResourceType.MOCK_RECORD)
    SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id="workspace-run",
        idempotency_key="workspace-run-key",
        status=SyncRun.Status.SUCCESS,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        fetched_count=2,
    )

    client = authenticated_client(user)
    jobs = client.get("/api/internal/integrations/workspace/", {"mode": "sync-jobs"})
    runs = client.get("/api/internal/integrations/workspace/", {"mode": "sync-runs"})

    assert jobs.status_code == 200
    assert jobs.json()["data"]["summary"]["job_count"] == 1
    assert jobs.json()["data"]["pagination"]["total"] == 1
    job_row = jobs.json()["data"]["results"][0]
    assert job_row["config_name"] == "tenant-a-config"
    assert job_row["account_alias"] == "tenant-a-config"
    assert job_row["query_mode"] == "incremental"
    assert job_row["lookback_days"] == 30
    assert job_row["query_page_size"] == 50
    assert job_row["max_records"] == 50000
    assert job_row["latest_fetched_count"] == 2
    assert job_row["latest_created_count"] == 0
    assert job_row["checkpoint_version"] is None
    assert runs.json()["data"]["summary"]["run_count"] == 1
    assert runs.json()["data"]["results"][0]["run_id"] == "workspace-run"


@pytest.mark.django_db
def test_integration_workspace_operation_endpoints_are_real_and_tenant_scoped():
    tenant = Tenant.objects.create(name="Tenant A", code="workspace-actions-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="workspace-actions-b")
    user = create_user(tenant, "workspace-actions-user")
    other_user = create_user(other_tenant, "workspace-actions-other")
    user.is_superuser = True
    user.is_staff = True
    user.save(update_fields=["is_superuser", "is_staff"])
    grant_integration_access(user)
    grant_integration_access(other_user)
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="mock",
        account_alias="workspace-actions-config",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.ACTIVE,
        created_by=user,
    )
    config.regions = ["TH"]
    config.credential_id = "custody://workspace-actions"
    config.credential_status = PlatformIntegrationConfig.CredentialStatus.CONFIGURED
    with authorization_service_write():
        config.save(update_fields=["regions", "credential_id", "credential_status", "updated_at"])
    job = SyncJob.objects.create(
        tenant=tenant,
        integration_config=config,
        resource_type=SyncJob.ResourceType.MOCK_RECORD,
        schedule_type=SyncJob.ScheduleType.MANUAL,
        status=SyncJob.Status.FAILED,
    )
    failed_run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id="workspace-actions-failed",
        idempotency_key="workspace-actions-failed-key",
        status=SyncRun.Status.FAILED,
        retry_count=0,
        masked_log={"execution_mode": "simulation"},
    )
    client = authenticated_client(user)

    created_config = client.post(
        "/api/internal/integrations/workspace-configs/",
        {"account_alias": "new-handoff-config", "platform": "shopee", "api_type": "marketplace", "environment": "sandbox", "regions": ["TH"]},
        format="json",
    )
    reference = client.post(f"/api/internal/integrations/configs/{config.id}/reference-check/", {}, format="json")
    consistency = client.post(f"/api/internal/integrations/configs/{config.id}/consistency-check/", {}, format="json")
    updated = client.patch(
        f"/api/internal/integrations/sync-jobs/{job.id}/",
        {
            "schedule_type": "daily",
            "max_retry_count": 8,
            "backoff_base_seconds": 2,
            "execution_mode": "simulation",
            "local_time": "03:30",
            "timezone": "Asia/Bangkok",
            "catch_up": "skip",
            "query_mode": "incremental",
            "lookback_days": 45,
            "overlap_minutes": 10,
            "query_page_size": 80,
            "max_pages": 120,
            "max_records": 60000,
            "query_statuses": "READY, SHIPPED",
        },
        format="json",
    )
    retried = client.post(f"/api/internal/integrations/sync-runs/{failed_run.id}/retry/", {}, format="json")

    assert created_config.status_code == 201
    assert created_config.json()["data"]["status"] == PlatformIntegrationConfig.Status.PENDING_REVIEW
    assert reference.status_code == 200
    assert reference.json()["data"]["external_api_called"] is False
    assert consistency.status_code == 200
    assert consistency.json()["data"]["checks"]["credential_reference"] is True
    assert updated.status_code == 200
    assert updated.json()["data"]["schedule_type"] == "daily"
    assert updated.json()["data"]["max_retry_count"] == 8
    assert retried.status_code == 201
    assert retried.json()["data"]["retry_count"] == 1
    assert retried.json()["data"]["masked_log"]["retry_of"] == failed_run.run_id
    assert authenticated_client(other_user).patch(
        f"/api/internal/integrations/sync-jobs/{job.id}/",
        {"max_retry_count": 2},
        format="json",
    ).status_code == 404


@pytest.mark.django_db
def test_sync_job_api_limits_backoff_base_seconds():
    tenant = Tenant.objects.create(name="Tenant", code="sync-backoff-limit")
    user = create_user(tenant, "tech")
    grant_integration_access(user)
    config = create_config(tenant, user)

    response = authenticated_client(user).post(
        "/api/internal/integrations/sync-jobs/",
        {
            "integration_config_id": config.id,
            "resource_type": "mock_record",
            "schedule_type": "manual",
            "backoff_base_seconds": 6,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_external_rpa_and_plain_internal_cannot_access_sync_api():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    internal = create_user(tenant, "plain")
    external = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa", CustomUser.UserType.RPA)

    assert APIClient().get("/api/internal/integrations/sync-jobs/").status_code == 401
    assert authenticated_client(internal).get("/api/internal/integrations/sync-jobs/").status_code == 403
    assert authenticated_client(external).get("/api/internal/integrations/sync-jobs/").status_code == 403
    assert authenticated_client(rpa).get("/api/internal/integrations/sync-jobs/").status_code == 403


@pytest.mark.django_db
def test_integration_view_permission_cannot_create_run_or_disable_sync_jobs():
    tenant = Tenant.objects.create(name="Tenant", code="sync-view-only")
    user = create_user(tenant, "sync-viewer")
    grant_integration_view_only(user)
    job = create_sync_job(tenant, user)
    client = authenticated_client(user)

    assert client.get("/api/internal/integrations/sync-jobs/").status_code == 200
    assert client.get("/api/internal/integrations/sync-runs/").status_code == 200
    assert (
        client.post(
            "/api/internal/integrations/sync-jobs/",
            {
                "integration_config_id": job.integration_config_id,
                "resource_type": "mock_record",
                "schedule_type": "manual",
            },
            format="json",
        ).status_code
        == 403
    )
    assert client.post(f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/", {}, format="json").status_code == 403
    assert client.post(f"/api/internal/integrations/sync-jobs/{job.id}/disable/", {}, format="json").status_code == 403

    job.refresh_from_db()
    assert job.is_enabled is True
    assert SyncRun.objects.filter(sync_job=job).count() == 0


@pytest.mark.django_db
def test_mock_sync_success_updates_cursor_and_masks_logs():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech")
    grant_integration_access(user)
    job = create_sync_job(tenant, user, alias="mock-shop")

    response = authenticated_client(user).post(
        f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/",
        {"idempotency_key": "tenant-job-run-1"},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created"] is True
    assert data["run"]["status"] == SyncRun.Status.SUCCESS
    assert data["run"]["fetched_count"] == 2
    assert data["run"]["skipped_count"] == 2
    assert SyncCursor.objects.get(sync_job=job, cursor_key="default").cursor_value == "done"
    assert "not-a-real-secret" not in json.dumps(data)
    assert "placeholder-token" not in json.dumps(data)


@pytest.mark.django_db
def test_idempotency_prevents_duplicate_sync_runs():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    client = authenticated_client(user)

    first = client.post(
        f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/",
        {"idempotency_key": "same-key"},
        format="json",
    )
    second = client.post(
        f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/",
        {"idempotency_key": "same-key"},
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["created"] is True
    assert second.json()["data"]["created"] is False
    assert SyncRun.objects.filter(tenant=tenant, idempotency_key="same-key").count() == 1


@pytest.mark.django_db
def test_idempotency_key_is_scoped_to_each_sync_job():
    tenant = Tenant.objects.create(name="Tenant", code="sync-job-idempotency-scope")
    user = create_user(tenant, "tech")
    grant_integration_access(user)
    first_job = create_sync_job(tenant, user, alias="mock-shop-a")
    second_job = create_sync_job(tenant, user, alias="mock-shop-b")
    client = authenticated_client(user)

    first = client.post(
        f"/api/internal/integrations/sync-jobs/{first_job.id}/run-mock/",
        {"idempotency_key": "shared-key"},
        format="json",
    )
    second = client.post(
        f"/api/internal/integrations/sync-jobs/{second_job.id}/run-mock/",
        {"idempotency_key": "shared-key"},
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["created"] is True
    assert second.json()["data"]["created"] is True
    assert first.json()["data"]["run"]["id"] != second.json()["data"]["run"]["id"]
    assert SyncRun.objects.filter(tenant=tenant, idempotency_key="shared-key").count() == 2
    assert SyncRun.objects.filter(sync_job=first_job, idempotency_key="shared-key").count() == 1
    assert SyncRun.objects.filter(sync_job=second_job, idempotency_key="shared-key").count() == 1


@pytest.mark.django_db
def test_finite_retry_and_max_retry_failure_are_recorded_without_waiting():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    job.max_retry_count = 2
    job.save(update_fields=["max_retry_count"])

    assert calculate_backoff_seconds(0, base_seconds=2) == 2
    assert calculate_backoff_seconds(2, base_seconds=2) == 8
    run = record_retry_failure(job, "api_secret not-a-real-secret failed", retry_count=2)

    assert run.status == SyncRun.Status.FAILED
    assert run.error_code == "MAX_RETRY_EXCEEDED"
    assert run.retry_count == 2
    assert "not-a-real-secret" not in run.masked_error_message


@pytest.mark.django_db
def test_transient_sync_failures_retry_with_backoff_without_sleeping():
    tenant = Tenant.objects.create(name="Tenant", code="sync-transient-retry")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    job.max_retry_count = 3
    job.backoff_base_seconds = 2
    job.save(update_fields=["max_retry_count", "backoff_base_seconds"])
    adapter = MockPlatformAdapter()
    original_fetch_page = adapter.fetch_page
    attempts = []
    retry_delays = []

    def flaky_fetch_page(sync_job, cursor_value=None):
        attempts.append(sync_job.next_run_at)
        if len(attempts) <= 2:
            raise RuntimeError("token=demo-transient-error")
        return original_fetch_page(sync_job, cursor_value)

    adapter.fetch_page = flaky_fetch_page
    run, created = run_sync_job(
        job,
        adapter=adapter,
        idempotency_key="transient-retry",
        retry_wait=retry_delays.append,
    )
    job.refresh_from_db()

    assert created is True
    assert len(attempts) == 3
    assert attempts[0] is None
    assert attempts[1] is not None
    assert attempts[2] is not None
    assert attempts[2] > attempts[1]
    assert retry_delays == [2, 4]
    assert run.status == SyncRun.Status.SUCCESS
    assert run.retry_count == 2
    assert run.error_code == ""
    assert run.masked_error_message == ""
    assert run.masked_log["retry_count"] == 2
    assert "demo-transient-error" not in json.dumps(run.masked_log)
    assert job.next_run_at is None


@pytest.mark.django_db
def test_sync_stops_after_configured_maximum_retries():
    tenant = Tenant.objects.create(name="Tenant", code="sync-max-retry")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    job.max_retry_count = 2
    job.save(update_fields=["max_retry_count"])
    adapter = MockPlatformAdapter()
    attempts = 0
    retry_delays = []

    def failing_fetch_page(sync_job, cursor_value=None):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("api_secret=not-a-real-secret")

    adapter.fetch_page = failing_fetch_page
    run, created = run_sync_job(
        job,
        adapter=adapter,
        idempotency_key="max-retry",
        retry_wait=retry_delays.append,
    )
    job.refresh_from_db()

    assert created is True
    assert attempts == 3
    assert retry_delays == [1, 2]
    assert run.status == SyncRun.Status.FAILED
    assert run.retry_count == 2
    assert run.error_code == "MAX_RETRY_EXCEEDED"
    assert "not-a-real-secret" not in run.masked_error_message
    assert job.status == SyncJob.Status.FAILED
    assert job.next_run_at is None


@pytest.mark.django_db
def test_retry_refreshes_cursor_after_transaction_rollback(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="sync-cursor-rollback")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    job.max_retry_count = 1
    job.save(update_fields=["max_retry_count"])
    adapter = MockPlatformAdapter()
    requested_cursors = []
    original_fetch_page = adapter.fetch_page
    original_run_save = SyncRun.save
    injected_failure = False

    def capture_cursor(sync_job, cursor_value=None):
        requested_cursors.append(cursor_value or "")
        return original_fetch_page(sync_job, cursor_value)

    def fail_once_after_cursor_save(run, *args, **kwargs):
        nonlocal injected_failure
        if run.status == SyncRun.Status.SUCCESS and not injected_failure:
            injected_failure = True
            raise RuntimeError("demo failure after cursor save")
        return original_run_save(run, *args, **kwargs)

    adapter.fetch_page = capture_cursor
    monkeypatch.setattr(SyncRun, "save", fail_once_after_cursor_save)

    run, created = run_sync_job(
        job,
        adapter=adapter,
        idempotency_key="cursor-rollback",
        retry_wait=lambda _delay: None,
    )

    assert created is True
    assert requested_cursors == ["", ""]
    assert run.status == SyncRun.Status.SUCCESS
    assert run.retry_count == 1
    assert run.fetched_count == 2
    assert run.skipped_count == 2
    assert SyncCursor.objects.get(sync_job=job, cursor_key="default").cursor_value == "done"


@pytest.mark.django_db
def test_sync_job_rejects_different_idempotency_key_while_run_is_active():
    tenant = Tenant.objects.create(name="Tenant", code="sync-active-run")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    now = timezone.now()
    job.status = SyncJob.Status.RUNNING
    job.last_run_at = now
    job.lock_token = "active-demo-run"
    job.lock_acquired_at = now
    job.lock_expires_at = now + timedelta(minutes=10)
    job.lock_heartbeat_at = now
    job.save(
        update_fields=[
            "status",
            "last_run_at",
            "lock_token",
            "lock_acquired_at",
            "lock_expires_at",
            "lock_heartbeat_at",
        ]
    )
    active_run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id="active-demo-run",
        idempotency_key="active-key",
        status=SyncRun.Status.RUNNING,
    )

    with pytest.raises(ValidationError, match="active run"):
        run_sync_job(
            job,
            adapter=MockPlatformAdapter(),
            idempotency_key="different-key",
            retry_wait=lambda _delay: None,
        )

    assert SyncRun.objects.filter(sync_job=job).get() == active_run


@pytest.mark.django_db
def test_expired_sync_job_lease_fails_old_run_and_allows_recovery():
    tenant = Tenant.objects.create(name="Tenant", code="sync-expired-lease")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user)
    stale_at = timezone.now() - timedelta(hours=24)
    job.status = SyncJob.Status.RUNNING
    job.last_run_at = stale_at
    job.save(update_fields=["status", "last_run_at"])
    stale_run = SyncRun.objects.create(
        tenant=tenant,
        sync_job=job,
        run_id="stale-demo-run",
        idempotency_key="stale-key",
        status=SyncRun.Status.RUNNING,
        started_at=stale_at,
    )

    recovered_run, created = run_sync_job(
        job,
        adapter=MockPlatformAdapter(),
        idempotency_key="recovery-key",
        retry_wait=lambda _delay: None,
    )
    stale_run.refresh_from_db()
    job.refresh_from_db()

    assert created is True
    assert stale_run.status == SyncRun.Status.FAILED
    assert stale_run.error_code == "LEASE_EXPIRED"
    assert stale_run.finished_at is not None
    assert recovered_run.status == SyncRun.Status.SUCCESS
    assert SyncRun.objects.filter(sync_job=job).count() == 2
    assert job.status == SyncJob.Status.IDLE
    assert job.lock_token == ""
    assert job.lock_expires_at is None
    assert job.lock_heartbeat_at is not None


@pytest.mark.django_db
def test_production_adapter_rejects_execution():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech")
    job = create_sync_job(tenant, user, environment=PlatformIntegrationConfig.Environment.PRODUCTION)
    adapter = DisabledProductionAdapter()

    with pytest.raises(ValidationError):
        adapter.fetch_page(job)


@pytest.mark.django_db
def test_run_mock_endpoint_rejects_sandbox_placeholder_adapter():
    tenant = Tenant.objects.create(name="Tenant", code="sandbox-tenant")
    user = create_user(tenant, "sandbox-tech")
    grant_integration_access(user)
    job = create_sync_job(
        tenant,
        user,
        environment=PlatformIntegrationConfig.Environment.SANDBOX,
        alias="sandbox-placeholder",
    )

    response = authenticated_client(user).post(
        f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/",
        {"idempotency_key": "sandbox-must-not-run"},
        format="json",
    )

    assert response.status_code == 400
    assert SyncRun.objects.filter(sync_job=job).count() == 0


@pytest.mark.django_db
def test_retry_error_masks_generic_credential_assignment():
    tenant = Tenant.objects.create(name="Tenant", code="masked-error-tenant")
    user = create_user(tenant, "masked-error-tech")
    job = create_sync_job(tenant, user)

    run = record_retry_failure(job, "token=demo-credential-value failed", retry_count=1)

    assert "demo-credential-value" not in run.masked_error_message
    assert "token=***" in run.masked_error_message


@pytest.mark.django_db
def test_disabled_sync_job_cannot_run():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "tech")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    client = authenticated_client(user)

    disable_response = client.post(f"/api/internal/integrations/sync-jobs/{job.id}/disable/", {}, format="json")
    run_response = client.post(f"/api/internal/integrations/sync-jobs/{job.id}/run-mock/", {}, format="json")

    assert disable_response.status_code == 200
    assert disable_response.json()["data"]["is_enabled"] is False
    assert run_response.status_code == 400


@pytest.mark.django_db
def test_webhook_event_deduplicates_by_tenant_platform_event_id():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    payload = {"event": "demo", "api_secret": "not-a-real-secret"}

    first, first_created = record_webhook_event(
        tenant,
        "mock",
        "event-001",
        "order.updated",
        payload,
        WebhookEvent.SignatureStatus.MOCK_VALID,
    )
    second, second_created = record_webhook_event(
        tenant,
        "mock",
        "event-001",
        "order.updated",
        payload,
        WebhookEvent.SignatureStatus.MOCK_VALID,
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert second.processing_status == WebhookEvent.ProcessingStatus.DUPLICATE
    assert WebhookEvent.objects.count() == 1
