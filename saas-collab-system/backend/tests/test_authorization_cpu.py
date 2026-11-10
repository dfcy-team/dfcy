"""CPU regression coverage for request-local authorization snapshot matching."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.accounts.serializers import CurrentUserSerializer
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def _grant(tenant, user, code, scope_type="all", valid_until=None, role_code=None):
    role = Role.objects.create(tenant=tenant, name=code, code=role_code or code.replace(".", "-"))
    permission, _ = Permission.objects.get_or_create(
        code=code, defaults={"name": code, "module": code.split(".")[0], "action": "view"}
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role, valid_until=valid_until)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={"all": True})
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code="products.master",
        permission_code=code, scope_type=scope_type, config={"all": True} if scope_type == "all" else {"sku_ids": [1]},
    )
    return role


def test_snapshot_resource_matching_is_deduplicated_and_preserves_multi_role_semantics(monkeypatch):
    tenant = Tenant.objects.create(name="CPU", code="auth-cpu")
    user = CustomUser.objects.create_user(username="cpu-member", tenant=tenant)
    role_a = _grant(tenant, user, "products.master.view")
    role_b = _grant(tenant, user, "products.master.view", role_code="second-role")
    extra_permission, _ = Permission.objects.get_or_create(
        code="products.master.export", defaults={"name": "export", "module": "products", "action": "view"}
    )
    role_b.permissions.add(extra_permission)
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role_b, resource_code="products.master",
        permission_code="*", scope_type="all", config={"all": True},
    )
    # Exact custom scope takes precedence over this role's wildcard all scope.
    RoleResourcePolicy.objects.filter(role=role_b, permission_code="products.master.view").update(
        scope_type="custom", config={"sku_ids": [1]},
    )

    from apps.accounts import serializers
    calls = []
    original = serializers.permission_resource

    def counted(code):
        calls.append(code)
        return original(code)

    monkeypatch.setattr(serializers, "permission_resource", counted)
    snapshot = CurrentUserSerializer(user)._authorization_snapshot(user)

    assert set(snapshot["roles"]) == {role_a.code, role_b.code}
    assert snapshot["permissions"] == ["products.master.export", "products.master.view"]
    # Role A's exact all grant keeps view in the union; role B's exact custom
    # grant overrides its wildcard all, while export remains all via wildcard.
    assert set(snapshot["all_scope_permission_codes"]) == {"products.master.view", "products.master.export"}
    assert len(calls) == 2  # one lookup per unique code, despite shared multi-role grants
    assert len(calls) < 3  # previous code resolved the shared grant once per role row
    role_a.permissions.clear()
    assert CurrentUserSerializer(user)._authorization_snapshot(user)["all_scope_permission_codes"] == ["products.master.export"]


def test_version_hash_matches_full_serializer_and_next_snapshot_sees_revocation_and_expiry(monkeypatch):
    tenant = Tenant.objects.create(name="CPU version", code="auth-cpu-version")
    user = CustomUser.objects.create_user(username="cpu-version", tenant=tenant)
    role = _grant(tenant, user, "products.master.view", valid_until=timezone.now() + timedelta(minutes=5))

    full = CurrentUserSerializer(user).data["authorization_version"]
    direct = CurrentUserSerializer(user).get_authorization_version(user)
    assert direct == full
    from apps.permissions.authorization import authorization_version
    assert authorization_version(user) == authorization_version(user, full)
    def disallow_full_serialization(*args, **kwargs):
        raise AssertionError("version polling must not serialize the full user")
    monkeypatch.setattr(CurrentUserSerializer, "to_representation", disallow_full_serialization)
    assert authorization_version(user) == authorization_version(user, full)

    binding = UserRole.objects.get(user=user, role=role)
    binding.status = "inactive"
    binding.save(update_fields=["status"])
    revoked = CurrentUserSerializer(user).get_authorization_version(user)
    assert revoked != full

    binding.status = "active"
    binding.save(update_fields=["status"])
    after_expiry = binding.valid_until + timedelta(seconds=1)
    monkeypatch.setattr(timezone, "now", lambda: after_expiry)
    expired_snapshot = CurrentUserSerializer(user)._authorization_snapshot(user)
    assert expired_snapshot["roles"] == []
    assert CurrentUserSerializer(user).get_authorization_version(user) != full
