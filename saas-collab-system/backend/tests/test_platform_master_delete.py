from unittest.mock import patch

import pytest

from apps.audit.models import OperationLog
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.tenants.models import Tenant
from tests.test_ui_p2_system_masterdata import client_for, create_user, grant


pytestmark = pytest.mark.django_db


@pytest.fixture
def platform_delete_context():
    tenant = Tenant.objects.create(code="platform-delete", name="Delete test")
    user = create_user(tenant, "platform-delete-manager")
    grant(user, "masterdata.manage")
    platform = PlatformMaster.objects.create(
        tenant=tenant, code="delete-test", name="Delete test", platform_type="other",
    )
    return tenant, user, platform


def test_platform_delete_removes_only_target_and_audits(platform_delete_context):
    tenant, user, platform = platform_delete_context
    pk = platform.pk
    client = client_for(user)
    response = client.delete(f"/api/internal/master-data/platforms/{pk}/")
    assert response.status_code == 200
    assert response.data["success"] is True
    assert not PlatformMaster.objects.filter(pk=pk).exists()
    log = OperationLog.objects.get(tenant=tenant, module="masterdata", action="delete", object_id=str(pk))
    assert log.user_id == user.pk
    assert log.before_data == {"code": "delete-test", "status": "active"}
    assert client.delete(f"/api/internal/master-data/platforms/{pk}/").status_code == 404


@pytest.mark.parametrize("reference", ["active_store", "inactive_store", "warehouse"])
def test_platform_delete_rejects_references(platform_delete_context, reference):
    tenant, user, platform = platform_delete_context
    if reference == "warehouse":
        related = WarehouseMaster.objects.create(
            tenant=tenant, service_platform=platform, code="ref", name="Ref",
            country_code="PH", warehouse_type="third_party",
        )
    else:
        related = StoreMaster.objects.create(
            tenant=tenant, platform=platform, code="ref", name="Ref",
            country_code="PH", currency="PHP",
            status="inactive" if reference == "inactive_store" else "active",
        )
    response = client_for(user).delete(f"/api/internal/master-data/platforms/{platform.pk}/")
    assert response.status_code == 409
    assert PlatformMaster.objects.filter(pk=platform.pk).exists()
    assert type(related).objects.filter(pk=related.pk).exists()
    assert not OperationLog.objects.filter(tenant=tenant, action="delete").exists()


def test_platform_delete_requires_permission_and_tenant(platform_delete_context):
    tenant, user, platform = platform_delete_context
    viewer = create_user(tenant, "platform-delete-viewer")
    grant(viewer, "masterdata.view")
    url = f"/api/internal/master-data/platforms/{platform.pk}/"
    assert client_for(viewer).delete(url).status_code == 403
    other = Tenant.objects.create(code="platform-delete-other", name="Other")
    outsider = create_user(other, "platform-delete-outsider")
    grant(outsider, "masterdata.manage")
    assert client_for(outsider).delete(url).status_code == 404
    assert PlatformMaster.objects.filter(pk=platform.pk).exists()


def test_platform_delete_rolls_back_when_audit_fails(platform_delete_context):
    _, user, platform = platform_delete_context
    with patch("apps.masterdata.views.write_operation_log", side_effect=RuntimeError("Synthetic audit failure")):
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            client_for(user).delete(f"/api/internal/master-data/platforms/{platform.pk}/")
    assert PlatformMaster.objects.filter(pk=platform.pk).exists()
