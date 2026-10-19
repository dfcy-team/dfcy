from io import StringIO

import pytest
from django.core.management import call_command

from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder
from apps.integrations.management.commands.simulate_tiktok_shop_readonly import ALIAS, SCOPE
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRawEnvelope, SyncRun
from apps.tenants.models import Tenant
from tests.test_phase2_sync_framework import create_user


pytestmark = pytest.mark.django_db


def test_demo_is_dry_run_by_default_and_isolated_when_applied():
    tenant = Tenant.objects.create(name="TK demo", code="tk-demo")
    user = create_user(tenant, "tk-demo-admin")
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])

    output = StringIO()
    call_command("simulate_tiktok_shop_readonly", username=user.username, stdout=output)
    assert "Dry run only" in output.getvalue()
    assert not PlatformIntegrationConfig.objects.filter(tenant=tenant).exists()

    call_command("simulate_tiktok_shop_readonly", username=user.username, apply=True, stdout=StringIO())
    config = PlatformIntegrationConfig.objects.get(tenant=tenant, account_alias=ALIAS)
    job = SyncJob.objects.get(integration_config=config)
    run = SyncRun.objects.get(sync_job=job)
    assert config.platform == "mock"
    assert config.environment == "mock"
    assert not config.network_enabled and not config.sync_read_enabled and not config.sync_write_enabled
    assert job.resource_type == "mock_record" and job.sync_scope == SCOPE
    assert run.status == "success"
    assert (run.fetched_count, run.created_count, run.skipped_count) == (4, 0, 4)
    assert SyncRawEnvelope.objects.filter(sync_run=run).count() == 1
    assert not SalesOrder.objects.filter(tenant=tenant).exists()
    assert not RefundReturn.objects.filter(tenant=tenant).exists()
    assert not InventorySnapshot.objects.filter(tenant=tenant).exists()

    call_command("simulate_tiktok_shop_readonly", username=user.username, apply=True, stdout=StringIO())
    assert SyncRun.objects.filter(sync_job=job).count() == 1
