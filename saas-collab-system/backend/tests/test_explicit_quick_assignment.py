import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def setup_target(code):
    tenant = Tenant.objects.create(name=f"Quick {code}", code=f"quick-{code}")
    administrator = sync_tenant_administrator_role(tenant)
    actor = CustomUser.objects.create_user(
        username=f"quick-{code}", password="test-password-123", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=actor, role=administrator)
    target = Role.objects.create(tenant=tenant, name="目标角色", code=f"target-{code}")
    DataScope.objects.create(tenant=tenant, role=target, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(actor)
    return client, target


def request_permissions(client, target, payload):
    return client.put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"scope_type": "all", "scope_config": {}, **payload},
        format="json",
    )


def test_quick_explicit_high_risk_requires_confirmation():
    client, target = setup_target("quick-reject")
    response = request_permissions(client, target, {
        "assignment_mode": "quick",
        "action_permission_codes": ["products.master.freeze"],
    })
    assert response.status_code == 400
    assert not target.permissions.exists()


def test_quick_explicit_high_risk_succeeds_when_confirmed():
    client, target = setup_target("quick-confirm")
    response = request_permissions(client, target, {
        "assignment_mode": "quick",
        "action_permission_codes": ["products.master.freeze"],
        "confirmed_high_risk_permission_codes": ["products.master.freeze"],
    })
    assert response.status_code == 200, response.content
    assert target.permissions.filter(code="products.master.freeze").exists()


def test_advanced_explicit_high_risk_remains_backward_compatible():
    client, target = setup_target("advanced-compatible")
    response = request_permissions(client, target, {
        "assignment_mode": "advanced",
        "action_permission_codes": ["products.master.freeze"],
    })
    assert response.status_code == 200, response.content
    assert target.permissions.filter(code="products.master.freeze").exists()


def test_legacy_package_confirmation_contract_remains_supported():
    client, target = setup_target("package-compatible")
    response = request_permissions(client, target, {
        "package_selections": {"products": "admin"},
        "extra_permission_codes": ["products.master.freeze"],
    })
    assert response.status_code == 200, response.content
    assert target.permissions.filter(code="products.master.freeze").exists()
