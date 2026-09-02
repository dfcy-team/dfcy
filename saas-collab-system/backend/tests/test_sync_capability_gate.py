import pytest
from types import SimpleNamespace
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import NotificationMessage, OperationLog
from apps.integrations.capability_gate import record_sync_source_decision, require_sync_read_capability, sync_source_health
from apps.integrations.models import (
    ConnectionCapability, MarketplaceStoreAuthorization, PlatformIntegrationConfig, SyncJob,
    authorization_service_write, marketplace_identity_key, marketplace_store_binding_key,
)
from apps.integrations.sync_services import run_sync_job
from apps.integrations.serializers import SyncJobSerializer
from apps.integrations.sync_alerts import resolve_sync_failure_alert, upsert_sync_failure_alert
from apps.integrations.scheduler import dispatch_due_jobs
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def make_job():
    tenant = Tenant.objects.create(name="Gate", code="capability-gate")
    user = CustomUser.objects.create_user(username="gate-user", password="not-real", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="shop", name="Shop", country_code="PH", currency="PHP")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="shopee", account_alias="gate", created_by=user)
    identity = marketplace_identity_key("shopee", "PH", "gate-shop")
    authorization = MarketplaceStoreAuthorization(
        tenant=tenant, integration_config=config, store=store, platform="shopee", region="PH",
        platform_store_id="gate-shop", platform_identity_key=identity, active_platform_identity_key=identity,
        active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
        merchant_subject_id="merchant", credential_id="credential-ref", token_id="token-ref",
        status=MarketplaceStoreAuthorization.Status.ACTIVE, created_by=user, updated_by=user,
    )
    with authorization_service_write():
        authorization.save()
    job = SyncJob.objects.create(
        tenant=tenant, integration_config=config, store_authorization=authorization,
        resource_type=SyncJob.ResourceType.SALES_ORDER,
    )
    return job, authorization


def grant_workspace_view(user):
    role = Role.objects.create(tenant=user.tenant, code="sync-health-view", name="Sync health view")
    for code in ("integrations.view", "integrations.config.view", "integrations.manage", "integrations.run"):
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": "view"},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={}
    )


def test_live_readonly_sync_requires_active_read_capability():
    job, authorization = make_job()
    assert sync_source_health(job)["state"] == "capability_missing"
    with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: ORDER"):
        require_sync_read_capability(job, "live_readonly")
    capability = ConnectionCapability.objects.create(
        authorization=authorization, capability_code="ORDER", read_enabled=True,
        write_enabled=False, status=ConnectionCapability.Status.ACTIVE, source_priority=5,
    )
    assert require_sync_read_capability(job, "live_readonly") == capability
    assert sync_source_health(job) == {
        "state": "ready", "capability_code": "ORDER", "source_priority": 5,
        "selected_authorization_id": authorization.id,
    }
    assert require_sync_read_capability(job, "mock") is None


def test_gate_runs_before_adapter_validation_or_fetch():
    job, _ = make_job()

    class Adapter:
        execution_mode = "live_readonly"
        validated = False

        def validate_configuration(self, sync_job):
            self.validated = True

    adapter = Adapter()
    with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: ORDER"):
        run_sync_job(job, adapter=adapter)
    assert adapter.validated is False


def test_selected_sync_source_is_audited_without_enabling_write():
    job, authorization = make_job()
    capability = ConnectionCapability.objects.create(
        authorization=authorization, capability_code="ORDER", read_enabled=True,
        write_enabled=False, status=ConnectionCapability.Status.ACTIVE, source_priority=7,
    )
    from apps.integrations.models import SyncRun
    run = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id="source-decision-run",
        idempotency_key="source-decision-key", status=SyncRun.Status.RUNNING,
    )
    log = record_sync_source_decision(job, run, capability)
    assert OperationLog.objects.filter(pk=log.pk, action="sync_source_selected").exists()
    assert log.after_data["authorization_id"] == authorization.id
    assert log.after_data["source_priority"] == 7
    assert log.after_data["candidate_count"] == 1
    assert log.after_data["write_enabled"] is False


def test_sync_failure_alert_is_deduplicated_and_resolved():
    job, _ = make_job()
    first, created = upsert_sync_failure_alert(
        job, error_code="CAPABILITY_NOT_ENABLED", message="token=must-not-leak"
    )
    NotificationMessage.objects.filter(pk=first.pk).update(status=NotificationMessage.Status.READ)
    second, created_again = upsert_sync_failure_alert(
        job, error_code="CAPABILITY_NOT_ENABLED", message="second failure"
    )
    assert created is True and created_again is False
    assert first.id == second.id
    assert NotificationMessage.objects.filter(
        message_type=f"sync_job_failure:{job.id}", status=NotificationMessage.Status.UNREAD
    ).count() == 1
    assert "must-not-leak" not in second.message
    assert resolve_sync_failure_alert(job) == 1
    second.refresh_from_db()
    assert second.status == NotificationMessage.Status.ARCHIVED


def test_scheduler_enqueue_failure_restores_due_time_and_alerts_operator():
    job, _ = make_job()
    due_at = timezone.now()
    job.schedule_type = SyncJob.ScheduleType.INTERVAL
    job.next_run_at = due_at
    job.save(update_fields=["schedule_type", "next_run_at", "updated_at"])

    def fail_enqueue(*_args):
        raise RuntimeError("placeholder-token")

    result = dispatch_due_jobs(fail_enqueue, now=due_at, limit=10)
    job.refresh_from_db()
    assert result["failed"] == 1
    assert job.next_run_at == due_at
    alert = NotificationMessage.objects.get(message_type=f"sync_job_failure:{job.id}")
    assert "placeholder-token" not in alert.message


def test_workspace_exposes_capability_block_and_scoped_open_alert_count():
    job, _ = make_job()
    user = job.integration_config.created_by
    grant_workspace_view(user)
    with authorization_service_write():
        PlatformIntegrationConfig.objects.filter(pk=job.integration_config_id).update(
            status=PlatformIntegrationConfig.Status.ACTIVE,
            credential_status="verified",
        )
    upsert_sync_failure_alert(job, error_code="CAPABILITY_NOT_ENABLED")
    client = APIClient(); client.force_authenticate(user)
    response = client.get("/api/internal/integrations/workspace/?mode=sync-jobs")
    assert response.status_code == 200
    assert response.data["data"]["summary"]["capability_blocked_job_count"] == 1
    assert response.data["data"]["summary"]["open_sync_alert_count"] == 1
    row = response.data["data"]["results"][0]
    assert row["health_state"] == "capability"
    assert row["capability_state"] == "capability_missing"
    assert row["blocked_reason"] == "所需只读能力尚未启用"


def test_sync_job_create_can_bind_scoped_store_authorization_for_page_closure():
    job, authorization = make_job()
    user = job.integration_config.created_by
    serializer = SyncJobSerializer(
        data={
            "integration_config_id": job.integration_config_id,
            "store_authorization_id": authorization.id,
            "resource_type": SyncJob.ResourceType.REFUND_RETURN,
            "schedule_type": SyncJob.ScheduleType.MANUAL,
            "is_enabled": False,
            "max_retry_count": 3,
            "backoff_base_seconds": 1,
        },
        context={"request": SimpleNamespace(user=user)},
    )
    serializer.is_valid(raise_exception=True)
    created = serializer.save(tenant=job.tenant)
    assert created.tenant_id == job.tenant_id
    assert created.integration_config_id == job.integration_config_id
    assert created.store_authorization_id == authorization.id
    assert created.is_enabled is False


def test_sync_incident_actions_and_confirmed_mock_retry_are_audited_and_idempotent():
    job, _ = make_job()
    user = job.integration_config.created_by
    grant_workspace_view(user)
    from apps.integrations.models import SyncAlertIncident, SyncRun
    failed = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id="incident-source-run",
        idempotency_key="incident-source-key", status=SyncRun.Status.FAILED,
        error_code="DEMO_FAILURE", masked_error_message="masked failure",
        masked_log={"execution_mode": "simulation"},
    )
    upsert_sync_failure_alert(job, sync_run=failed)
    incident = SyncAlertIncident.objects.get(sync_job=job)
    client = APIClient(); client.force_authenticate(user)

    collection = client.get("/api/internal/integrations/sync-alert-incidents/")
    assert collection.status_code == 200
    assert collection.data["data"][0]["occurrence_count"] == 1
    action_url = f"/api/internal/integrations/sync-alert-incidents/{incident.id}/action/"
    acknowledged = client.post(action_url, {"action": "acknowledge", "note": "正在排查"}, format="json")
    assert acknowledged.status_code == 200
    assigned = client.post(
        action_url, {"action": "assign", "assignee_id": user.id, "note": "由创建人处理"}, format="json"
    )
    assert assigned.status_code == 200
    assert assigned.data["data"]["assignee"] == user.id

    retry_url = f"/api/internal/integrations/sync-alert-incidents/{incident.id}/retry/"
    preview = client.get(retry_url)
    assert preview.status_code == 200
    assert preview.data["data"]["allowed"] is True
    assert preview.data["data"]["external_api_called"] is False
    assert client.post(
        retry_url, {"confirmed": False, "idempotency_key": "incident-retry-001"}, format="json"
    ).status_code == 400
    payload = {"confirmed": True, "idempotency_key": "incident-retry-001"}
    executed = client.post(retry_url, payload, format="json")
    replay = client.post(retry_url, payload, format="json")
    assert executed.status_code == 201 and executed.data["data"]["created"] is True
    assert replay.status_code == 200 and replay.data["data"]["created"] is False
    assert executed.data["data"]["run"]["id"] == replay.data["data"]["run"]["id"]
    incident.refresh_from_db()
    assert incident.status == SyncAlertIncident.Status.RESOLVED
    assert OperationLog.objects.filter(
        tenant=job.tenant, action__in=("acknowledge_sync_incident", "assign_sync_incident")
    ).count() == 2


def test_production_or_live_incident_retry_is_fail_closed():
    job, _ = make_job()
    user = job.integration_config.created_by
    grant_workspace_view(user)
    from apps.integrations.models import SyncRun
    PlatformIntegrationConfig.objects.filter(pk=job.integration_config_id).update(
        environment=PlatformIntegrationConfig.Environment.PRODUCTION
    )
    failed = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id="live-source-run",
        idempotency_key="live-source-key", status=SyncRun.Status.FAILED,
        masked_log={"execution_mode": "live_readonly"},
    )
    upsert_sync_failure_alert(job, sync_run=failed)
    incident = job.alert_incident
    client = APIClient(); client.force_authenticate(user)
    response = client.get(f"/api/internal/integrations/sync-alert-incidents/{incident.id}/retry/")
    assert response.status_code == 200
    assert response.data["data"]["allowed"] is False
    assert "Mock 或沙箱" in response.data["data"]["blocked_reason"]
