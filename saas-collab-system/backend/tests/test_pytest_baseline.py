import pytest
from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import APISyncTask, PlatformChoices
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant
from tests.factories import create_internal_user, create_rpa_agent, create_tenant


def test_django_settings_module_is_dev():
    assert settings.SETTINGS_MODULE == "config.settings.dev"


def test_django_configuration_check_passes():
    call_command("check")


@pytest.mark.django_db
def test_test_factories_create_tenant_internal_user_and_rpa_agent():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)
    agent = create_rpa_agent(tenant=tenant)

    assert tenant.id is not None
    assert user.user_type == CustomUser.UserType.INTERNAL
    assert user.tenant == tenant
    assert agent.tenant == tenant


@pytest.mark.django_db
def test_baseline_tenant_model():
    tenant = create_tenant(name="Baseline Tenant", code="baseline-tenant")

    assert Tenant.objects.filter(code="baseline-tenant").exists()
    assert tenant.status == Tenant.Status.ACTIVE


@pytest.mark.django_db
def test_baseline_custom_user_model():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant, email="baseline@example.com")

    assert user.id is not None
    assert user.email == "baseline@example.com"
    assert user.tenant_id == tenant.id


@pytest.mark.django_db
def test_baseline_api_health_route():
    response = APIClient().get("/api/internal/health/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {"status": "ok", "service": "internal"},
    }


@pytest.mark.django_db
def test_baseline_rpa_task_model_uses_weak_business_reference():
    tenant = create_tenant()
    agent = create_rpa_agent(tenant=tenant)
    task = RPATask.objects.create(
        tenant=tenant,
        task_type="baseline_check",
        business_type="purchase_order",
        business_id="PO-BASELINE",
        claimed_by=agent,
    )

    assert task.status == RPATask.Status.PENDING
    assert task.business_type == "purchase_order"
    assert task.business_id == "PO-BASELINE"


@pytest.mark.django_db
def test_baseline_api_sync_task_model_uses_placeholder_config_only():
    tenant = create_tenant()
    task = APISyncTask.objects.create(
        tenant=tenant,
        platform=PlatformChoices.BIGSELLER,
        sync_type=APISyncTask.SyncType.INVENTORY,
        config={"source": "test-placeholder"},
    )

    assert task.status == APISyncTask.Status.PENDING
    assert task.config == {"source": "test-placeholder"}
