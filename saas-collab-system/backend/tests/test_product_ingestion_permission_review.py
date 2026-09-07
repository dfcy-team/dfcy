"""Independent acceptance of the new resource's least-privilege boundary."""

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.capability_gate import require_sync_read_capability
from apps.integrations.models import ConnectionCapability, SyncJob
from apps.integrations.sync_services import run_sync_job
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.ui_p6_scopes import filter_sync_jobs, integration_values_allowed
from tests.test_sync_capability_gate import make_job


pytestmark = pytest.mark.django_db


def _grant(user, resource):
    role = Role.objects.create(tenant=user.tenant, code="product-review", name="Product review")
    permission, _ = Permission.objects.get_or_create(
        code="integrations.run_live_readonly",
        defaults={"name": "Readonly run", "module": "integrations", "action": "run"},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    return DataScope.objects.create(
        tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"resource_types": [resource]},
    )


def test_order_only_role_cannot_run_or_see_product_jobs():
    job, _ = make_job()
    job.resource_type = "platform_product"
    job.save(update_fields=["resource_type"])
    user = job.integration_config.created_by
    _grant(user, "sales_order")
    assert not integration_values_allowed(
        user, "integrations.run_live_readonly", resource_type="platform_product",
    )
    assert not filter_sync_jobs(
        user, SyncJob.objects.filter(pk=job.pk), "integrations.run_live_readonly",
    ).exists()


def test_product_scope_does_not_grant_order_resource():
    job, _ = make_job()
    user = job.integration_config.created_by
    _grant(user, "platform_product")
    assert integration_values_allowed(
        user, "integrations.run_live_readonly", resource_type="platform_product",
    )
    assert not integration_values_allowed(
        user, "integrations.run_live_readonly", resource_type="sales_order",
    )


def test_order_capability_cannot_authorize_product_read_before_network():
    job, authorization = make_job()
    job.resource_type = "platform_product"
    job.save(update_fields=["resource_type"])
    ConnectionCapability.objects.create(
        authorization=authorization, capability_code="ORDER", read_enabled=True,
        write_enabled=False, status=ConnectionCapability.Status.ACTIVE,
    )

    class MustNotReachNetwork:
        execution_mode = "live_readonly"

        def validate_configuration(self, _job):
            pytest.fail("PRODUCT capability must be checked before client validation/network")

    with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: PRODUCT"):
        run_sync_job(job, adapter=MustNotReachNetwork())
    capability = ConnectionCapability.objects.create(
        authorization=authorization, capability_code="PRODUCT", read_enabled=True,
        write_enabled=False, status=ConnectionCapability.Status.ACTIVE,
    )
    assert require_sync_read_capability(job, "live_readonly") == capability
    capability.write_enabled = True
    capability.save(update_fields=["write_enabled"])
    with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: PRODUCT"):
        require_sync_read_capability(job, "live_readonly")
