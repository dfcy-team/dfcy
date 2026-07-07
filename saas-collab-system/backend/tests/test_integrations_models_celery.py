import pytest
from django.conf import settings

from apps.integrations.models import (
    APIDataQualityCheck,
    APIIntegrationConfig,
    APISyncLog,
    APISyncTask,
    PlatformChoices,
)
from config.celery import app, debug_task
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_api_integration_config_can_be_created_without_real_secrets():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    config = APIIntegrationConfig.objects.create(
        tenant=tenant,
        platform=PlatformChoices.BIGSELLER,
        shop_code="shop-001",
        api_base_url="https://api.example.test",
        api_key_encrypted="encrypted-placeholder-key",
        api_secret_encrypted="encrypted-placeholder-secret",
    )

    assert config.id is not None
    assert config.status == APIIntegrationConfig.Status.ACTIVE
    assert "real" not in config.api_key_encrypted.lower()


@pytest.mark.django_db
def test_api_sync_task_status_and_log_can_be_recorded():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    task = APISyncTask.objects.create(
        tenant=tenant,
        platform=PlatformChoices.SHOPEE,
        sync_type=APISyncTask.SyncType.SALES_ORDER,
        status=APISyncTask.Status.PENDING,
        config={"page_size": 100},
    )
    log = APISyncLog.objects.create(
        tenant=tenant,
        task=task,
        status=APISyncTask.Status.SUCCESS,
        request_url="https://api.example.test/orders",
        request_payload={"cursor": None},
        response_summary={"records": 10},
    )
    quality_check = APIDataQualityCheck.objects.create(
        tenant=tenant,
        sync_log=log,
        check_type="required_fields",
        status=APIDataQualityCheck.Status.PASSED,
        details={"missing": []},
    )

    assert task.status == APISyncTask.Status.PENDING
    assert log.response_summary == {"records": 10}
    assert quality_check.status == APIDataQualityCheck.Status.PASSED


@pytest.mark.django_db
def test_api_sync_task_enums_are_limited_to_sync_center_scope():
    assert {value for value, _ in APISyncTask.SyncType.choices} == {
        "sales_order",
        "inventory",
        "inbound",
        "shipment",
        "settlement_bill",
        "withdrawal",
    }
    assert "price_confirmation" not in {value for value, _ in APISyncTask.SyncType.choices}


def test_celery_is_configured_with_redis_broker():
    assert settings.CELERY_BROKER_URL.startswith("redis://")
    assert app.conf.broker_url.startswith("redis://")
    assert debug_task.name == "config.celery.debug_task"
