"""Review regression contracts; all platform/custody traffic is synthetic."""
from datetime import date, timedelta
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, close_old_connections, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations import ads_sync, ads_capability_api, sync_services, tiktok_ads_pilot as pilot
from apps.integrations.models import SyncJob, SyncCheckpoint, SyncRun, TikTokAdsDailySpend, TikTokAdsSyncLease
from apps.integrations.scheduler import resume_due_sync_runs
from apps.integrations.serializers import SyncJobSerializer
from apps.integrations.tests.test_ads_standard_sync import ctx, Http, execute, api
from apps.permissions.models import Role, Permission, UserRole, DataScope

pytestmark = pytest.mark.django_db


def test_module_off_preflight_has_no_http_no_custody_no_checkpoint(ctx, monkeypatch):
    monkeypatch.setattr(ads_sync, "is_module_enabled", lambda _: False)
    http = Http()
    with pytest.raises(ValidationError):
        execute(ctx, http)
    assert not http.calls
    ctx.custody.retrieve_access_token.assert_not_called()
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_revocation_during_custody_resolution_prevents_first_account_http(ctx):
    def revoke(_):
        type(ctx.mappings[0]).objects.filter(pk=ctx.mappings[0].pk).update(enabled=False)
        return "SYNTHETIC_ONLY"
    ctx.custody.retrieve_access_token.side_effect = revoke
    http = Http()
    assert execute(ctx, http).status == "failed"
    assert not http.calls and not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


@pytest.mark.parametrize("change", ["module", "mapping", "config", "binding", "job", "lease"])
def test_revocation_after_account_http_stops_all_report_http(ctx, monkeypatch, change):
    enabled = [True]
    monkeypatch.setattr(ads_sync, "is_module_enabled", lambda _: enabled[0])
    class StopAfterAccount(Http):
        def request(self, *args, **kwargs):
            assert kwargs["retry"] is False  # No unguarded transport retry.
            result = super().request(*args, **kwargs)
            if len(self.calls) == 1:
                if change == "module":
                    enabled[0] = False
                elif change == "mapping":
                    type(ctx.mappings[0]).objects.filter(pk=ctx.mappings[0].pk).update(enabled=False)
                elif change == "config":
                    type(ctx.config).objects.filter(pk=ctx.config.pk).update(sync_read_enabled=False)
                elif change == "binding":
                    type(ctx.session).objects.filter(pk=ctx.session.pk).update(status="failed")
                elif change == "job":
                    SyncJob.objects.filter(pk=ctx.job.pk).update(lock_token="test-lost-fence")
                else:
                    TikTokAdsSyncLease.objects.filter(tenant=ctx.tenant).update(generation=999)
            return result
    http = StopAfterAccount()
    ctx.job.max_retry_count = 3
    ctx.job.save()
    if change == "job":
        with pytest.raises(ValidationError):
            execute(ctx, http)
    else:
        run = execute(ctx, http)
        assert run.status == "failed" and run.retry_count == 0
        assert not run.masked_log["runtime_budget"]["pending"]
    assert len(http.calls) == 1
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_revocation_after_first_report_stops_next_page(ctx, monkeypatch):
    class PaginatedStop(Http):
        def request(self, *args, **kwargs):
            result = super().request(*args, **kwargs)
            if len(self.calls) == 2:
                type(ctx.mappings[0]).objects.filter(pk=ctx.mappings[0].pk).update(enabled=False)
                return SimpleNamespace(json=lambda: {"code": 0, "data": {
                    "page_info": {"page": 1, "total_page": 2, "total_number": 1001},
                    "list": [{"dimensions": {"campaign_id": str(i)}, "metrics": {"spend": "0"}} for i in range(1000)]}})
            return result
    http = PaginatedStop()
    run = execute(ctx, http)
    assert run.status == "failed" and len(http.calls) == 2
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_module_disabled_after_collection_cannot_commit(ctx, monkeypatch):
    enabled = [True]
    monkeypatch.setattr(ads_sync, "is_module_enabled", lambda _: enabled[0])
    archive = sync_services.archive_raw_page
    def stop_before_commit(*args):
        result = archive(*args)
        enabled[0] = False
        return result
    monkeypatch.setattr(sync_services, "archive_raw_page", stop_before_commit)
    http = Http()
    run = execute(ctx, http)
    assert run.status == "failed" and len(http.calls) == 8
    assert not run.raw_envelopes.exists()
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_module_disabled_during_upsert_rolls_back_all_rows(ctx, monkeypatch):
    enabled = [True]
    monkeypatch.setattr(ads_sync, "is_module_enabled", lambda _: enabled[0])
    original = TikTokAdsDailySpend.objects.update_or_create
    def stop(*args, **kwargs):
        result = original(*args, **kwargs)
        enabled[0] = False
        return result
    monkeypatch.setattr(TikTokAdsDailySpend.objects, "update_or_create", stop)
    assert execute(ctx).status == "failed"
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_two_accounts_contention_resumes_original_window_next_day_without_provider_retry(ctx, monkeypatch):
    old_now = timezone.now().replace(hour=23, minute=59, second=0, microsecond=0)
    monkeypatch.setattr(ads_sync.timezone, "now", lambda: old_now)
    second = SyncJob.objects.create(tenant=ctx.tenant, integration_config=ctx.config, ads_mapping=ctx.mappings[1],
        resource_type="advertising_report", is_enabled=True, max_retry_count=0,
        sync_scope={"execution_mode": "live_readonly", "query": {"mode": "incremental", "lookback_days": 7}})
    waiting = []
    def compete():
        run, _ = sync_services.run_sync_job(second, idempotency_key="account-two-wait")
        waiting.append(run.pk)
    http = Http(hook=compete)
    assert execute(ctx, http).status == "success"
    run = SyncRun.objects.get(pk=waiting[0])
    assert run.status == "queued" and run.error_code == "ADS_LEASE_BUSY" and run.retry_count == 0
    assert not SyncCheckpoint.objects.filter(sync_job=second).exists()
    frozen = dict(run.masked_log["runtime_budget"]["resolved_scope"])
    assert "last_page_committed_at" not in run.masked_log["runtime_budget"]
    stale, created = sync_services.run_sync_job(second, idempotency_key="account-two-wait", resume_sequence=0)
    assert stale.pk == run.pk and not created and stale.status == "queued"
    next_day = old_now + timedelta(minutes=2)
    monkeypatch.setattr(ads_sync.timezone, "now", lambda: next_day)
    submitted = []
    assert resume_due_sync_runs(lambda *args: submitted.append(args), now=next_day) == 1
    assert submitted == [(second.pk, "account-two-wait", 1)]
    next_http = Http()
    monkeypatch.setattr(pilot, "PlatformHttpClient", lambda: next_http)
    resumed, _ = sync_services.run_sync_job(second, idempotency_key="account-two-wait", resume_sequence=1)
    assert resumed.pk == run.pk and resumed.status == "success" and resumed.retry_count == 0
    assert resumed.masked_log["runtime_budget"]["resolved_scope"] == frozen
    assert set(TikTokAdsDailySpend.objects.filter(mapping=ctx.mappings[1]).values_list("date", flat=True)) == {
        date.fromisoformat(frozen["start_date"]) + timedelta(days=i) for i in range(7)}
    assert not resumed.masked_log["ads_lease_wait"]["active"]
    second.refresh_from_db()
    assert second.sync_scope["query"] == {"mode": "incremental", "lookback_days": 7}


def test_pilot_contention_wait_is_bounded_and_does_not_burn_retry_budget(ctx, monkeypatch):
    owner, generation = pilot._claim_lease(ctx.tenant.pk)
    http = Http()
    run = execute(ctx, http)
    assert run.error_code == "ADS_LEASE_BUSY" and not http.calls and run.retry_count == 0
    then = timezone.now() + timedelta(seconds=ads_sync.LEASE_WAIT_SECONDS + 1)
    monkeypatch.setattr(ads_sync.timezone, "now", lambda: then)
    TikTokAdsSyncLease.objects.filter(tenant=ctx.tenant).update(lease_expires_at=then + timedelta(minutes=15))
    failed, _ = sync_services.run_sync_job(ctx.job, idempotency_key=run.idempotency_key, resume_sequence=1)
    assert failed.status == "failed" and failed.error_code == "ADS_LEASE_WAIT_TIMEOUT" and failed.retry_count == 0
    assert not failed.masked_log["ads_lease_wait"]["active"]
    assert not http.calls and not SyncCheckpoint.objects.exists()
    pilot._release_lease(ctx.tenant.pk, owner, generation)


def test_repeated_busy_resumes_keep_original_deadline_and_checkpoint(ctx, monkeypatch):
    owner, generation = pilot._claim_lease(ctx.tenant.pk)
    run = execute(ctx)
    original = dict(run.masked_log["ads_lease_wait"])
    frozen = dict(run.masked_log["runtime_budget"]["resolved_scope"])
    then = timezone.now() + timedelta(minutes=2)
    monkeypatch.setattr(ads_sync.timezone, "now", lambda: then)
    queued, _ = sync_services.run_sync_job(ctx.job, idempotency_key=run.idempotency_key, resume_sequence=1)
    assert queued.status == "queued" and queued.error_code == "ADS_LEASE_BUSY" and queued.retry_count == 0
    assert queued.masked_log["ads_lease_wait"] == original
    assert queued.masked_log["runtime_budget"]["resolved_scope"] == frozen
    assert queued.masked_log["runtime_budget"]["sequence"] == 2
    assert not SyncCheckpoint.objects.exists()
    pilot._release_lease(ctx.tenant.pk, owner, generation)


def test_ordinary_view_permission_cannot_access_api_admin_capabilities(ctx):
    viewer = get_user_model().objects.create_user(username="ads-real-viewer", tenant=ctx.tenant, user_type="internal")
    permission, _ = Permission.objects.get_or_create(code="integrations.store.view", defaults={
        "name": "View stores", "module": "integrations", "action": "view"})
    role = Role.objects.create(tenant=ctx.tenant, code="ads-view-only", name="Ads view only")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=ctx.tenant, user=viewer, role=role)
    DataScope.objects.create(tenant=ctx.tenant, role=role, scope_type="custom", config={"store_ids": [ctx.stores[0].pk]})
    context = SimpleNamespace(actor=viewer)
    response = api(ads_capability_api.capabilities, context)
    assert response.status_code == 403, response.data
    assert api(ads_capability_api.capability, context, "put", {"read_enabled": False}, pk=ctx.mappings[0].pk).status_code == 403
    ctx.custody.retrieve_access_token.assert_not_called()


@pytest.mark.parametrize("budget", [60, 240, 720])
def test_ads_budget_rejected_by_create_patch_preview_and_executor(ctx, budget):
    from apps.integrations.views import sync_job_detail, preview_sync_schedule
    serializer = SyncJobSerializer(data={"integration_config_id": ctx.config.pk, "ads_mapping_id": ctx.mappings[1].pk,
        "resource_type": "advertising_report", "execution_budget_seconds": budget}, context={"request": SimpleNamespace(user=ctx.actor)})
    assert not serializer.is_valid()
    assert api(sync_job_detail, ctx, "patch", {"execution_budget_seconds": budget}, pk=ctx.job.pk).status_code == 400
    assert api(preview_sync_schedule, ctx, "post", {"execution_budget_seconds": budget}, pk=ctx.job.pk).status_code == 400
    ctx.job.sync_scope["schedule"] = {"execution_budget_seconds": budget}
    ctx.job.save()
    with pytest.raises(ValidationError):
        execute(ctx)


def test_zero_ads_budget_and_other_resource_budget_are_unchanged(ctx):
    from apps.integrations.views import _set_job_scope
    _set_job_scope(ctx.job, {"execution_budget_seconds": 0})
    ordinary = SyncJob(tenant=ctx.tenant, integration_config=ctx.config, resource_type="sales_order")
    _set_job_scope(ordinary, {"execution_budget_seconds": 240})
    assert ordinary.sync_scope["schedule"]["execution_budget_seconds"] == 240


def module_definition():
    from apps.configcenter.models import SystemConfigDefinition
    from apps.integrations.module_release import MODULE_RELEASE_CONFIG_KEY
    definition, _ = SystemConfigDefinition.objects.get_or_create(config_key=MODULE_RELEASE_CONFIG_KEY,
        defaults={"scope_type": "system", "value_type": "json", "requires_approval": False})
    if definition.requires_approval:
        definition.requires_approval = False
        definition.save(update_fields=["requires_approval"])
    return definition


def publish_module(definition, actor, state):
    from apps.configcenter.services import create_config_version
    from apps.integrations.module_release import DEFAULT_MODULES
    return create_config_version(definition=definition, actor=actor,
        value={"modules": {**DEFAULT_MODULES, "api_integrations": state}}, effective_at=timezone.now())


@pytest.mark.parametrize("state", ["disabled", "mock_only"])
def test_current_module_version_fence_rejects_disabled_even_if_snapshot_gate_says_enabled(ctx, state):
    definition = module_definition()
    publish_module(definition, ctx.actor, state)
    # The fixture deliberately leaves the ordinary/global gate enabled.
    with transaction.atomic(), pytest.raises(ValidationError):
        ads_sync.lock_runtime_approval()


@pytest.mark.parametrize("state", ["enabled", "pilot_readonly"])
def test_current_module_version_fence_accepts_readable_states(ctx, state):
    definition = module_definition()
    publish_module(definition, ctx.actor, state)
    with transaction.atomic():
        ads_sync.lock_runtime_approval()


@pytest.mark.django_db(transaction=True)
def test_mysql_repeatable_read_new_module_disable_between_fetch_and_commit_is_current_read(ctx, monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("requires isolated MySQL repeatable-read two-connection acceptance")
    from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion
    definition = module_definition()
    enabled = publish_module(definition, ctx.actor, "enabled")
    original_archive = sync_services.archive_raw_page
    observed = []
    def publish_disabled_elsewhere():
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=ctx.actor.pk)
            target = SystemConfigDefinition.objects.get(pk=definition.pk)
            return publish_module(target, actor, "disabled").pk
        finally:
            close_old_connections()
    def archive_then_disable(*args):
        result = original_archive(*args)
        assert connection.in_atomic_block
        assert TenantConfigVersion.objects.get(definition=definition, status="effective").pk == enabled.pk
        with ThreadPoolExecutor(max_workers=1) as pool:
            observed.append(pool.submit(publish_disabled_elsewhere).result(timeout=15))
        # Ordinary reads still see the earlier enabled approval in this exact
        # page transaction; only the version FOR UPDATE can see the new stop.
        assert TenantConfigVersion.objects.get(definition=definition, status="effective").pk == enabled.pk
        return result
    monkeypatch.setattr(sync_services, "archive_raw_page", archive_then_disable)
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@transaction_isolation")
        previous = cursor.fetchone()[0]
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    try:
        run = execute(ctx)
        assert observed and run.status == "failed" and run.error_code == "ADS_SYNC_STOPPED"
        assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()
        assert not run.raw_envelopes.exists()
    finally:
        levels = {"READ-COMMITTED": "READ COMMITTED", "REPEATABLE-READ": "REPEATABLE READ",
                  "READ-UNCOMMITTED": "READ UNCOMMITTED", "SERIALIZABLE": "SERIALIZABLE"}
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL " + levels[previous])


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("stop", ["readonly_sync_enabled", "security_approved", "contract_approved"])
def test_mysql_global_runtime_stop_is_current_even_with_independent_enabled_module(ctx, monkeypatch, stop):
    if connection.vendor != "mysql":
        pytest.skip("requires isolated MySQL repeatable-read two-connection acceptance")
    from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion
    from apps.configcenter.services import create_config_version
    from apps.integrations.production_settings import CONFIG_KEY, SAFE_DEFAULTS
    publish_module(module_definition(), ctx.actor, "enabled")
    definition, _ = SystemConfigDefinition.objects.get_or_create(config_key=CONFIG_KEY,
        defaults={"scope_type": "system", "value_type": "json", "requires_approval": False})
    definition.requires_approval = False
    definition.save(update_fields=["requires_approval"])
    value = deepcopy(SAFE_DEFAULTS)
    value["network"].update(mode="approved-live-test", security_approved=True,
        readonly_sync_enabled=True, allowed_hosts=["business-api.tiktok.com"])
    value["platforms"]["tiktok"]["contract_approved"] = True
    enabled = create_config_version(definition=definition, actor=ctx.actor, value=value, effective_at=timezone.now())
    stopped = deepcopy(value)
    if stop == "contract_approved":
        stopped["platforms"]["tiktok"][stop] = False
    else:
        stopped["network"][stop] = False
    original_archive = sync_services.archive_raw_page
    observed = []
    def revoke_elsewhere():
        close_old_connections()
        try:
            return create_config_version(definition=SystemConfigDefinition.objects.get(pk=definition.pk),
                actor=get_user_model().objects.get(pk=ctx.actor.pk), value=stopped, effective_at=timezone.now()).pk
        finally:
            close_old_connections()
    def archive_then_stop(*args):
        result = original_archive(*args)
        assert TenantConfigVersion.objects.get(definition=definition, status="effective").pk == enabled.pk
        with ThreadPoolExecutor(max_workers=1) as pool:
            observed.append(pool.submit(revoke_elsewhere).result(timeout=15))
        assert TenantConfigVersion.objects.get(definition=definition, status="effective").pk == enabled.pk
        return result
    monkeypatch.setattr(sync_services, "archive_raw_page", archive_then_stop)
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@transaction_isolation")
        previous = cursor.fetchone()[0]
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    try:
        run = execute(ctx)
        assert observed and run.status == "failed" and run.error_code == "ADS_SYNC_STOPPED"
        assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()
        assert not run.raw_envelopes.exists()
    finally:
        levels = {"READ-COMMITTED": "READ COMMITTED", "REPEATABLE-READ": "REPEATABLE READ",
                  "READ-UNCOMMITTED": "READ UNCOMMITTED", "SERIALIZABLE": "SERIALIZABLE"}
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL " + levels[previous])
