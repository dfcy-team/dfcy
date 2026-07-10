import json

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.adapters import DisabledProductionAdapter
from apps.integrations.models import (
    PlatformIntegrationConfig,
    SyncCursor,
    SyncJob,
    SyncRun,
    WebhookEvent,
)
from apps.integrations.sync_services import calculate_backoff_seconds, record_retry_failure, record_webhook_event
from apps.permissions.models import Permission, Role, UserRole
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


def grant_integration_view_only(user):
    role = Role.objects.create(tenant=user.tenant, name="Integration Viewer", code=f"integration-viewer-{user.id}")
    permission, _created = Permission.objects.get_or_create(
        code="integrations.view",
        defaults={"name": "View integrations", "module": "integrations", "action": "view"},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_config(tenant, user, environment=PlatformIntegrationConfig.Environment.MOCK, alias="demo-sync"):
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
