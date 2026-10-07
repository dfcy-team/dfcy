"""Behavioral acceptance tests for the authorization workbench APIs."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, OrgMembership, Permission, PermissionChange, Role, RoleResourcePolicy, UserRole
from apps.tenants.models import Department, Tenant

pytestmark = pytest.mark.django_db


def setup_tenant(code="auth-workbench"):
    tenant = Tenant.objects.create(name=code, code=code)
    actor = CustomUser.objects.create_superuser(username=f"admin-{code}", password="test-password", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL)
    client = APIClient()
    client.force_authenticate(actor)
    return tenant, actor, client


def user(tenant, username):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def role(tenant, code, permissions=()):
    result = Role.objects.create(tenant=tenant, name=code, code=code)
    for code_value in permissions:
        permission, _ = Permission.objects.get_or_create(code=code_value, defaults={"name": code_value,
            "module": code_value.split(".")[0], "action": "manage"})
        result.permissions.add(permission)
    return result


def preview(client, ids, roles, operation="transfer", source="position"):
    return client.post("/api/internal/system/authorization/batches/preview/", {
        "user_ids": ids, "role_codes": roles, "operation": operation,
        "replace_source": source, "reason": "acceptance test change",
    }, format="json")


def apply(client, token):
    return client.post("/api/internal/system/authorization/batches/apply/", {"preview_token": token}, format="json")


def test_twenty_member_transfer_preserves_other_source_and_retry_is_idempotent():
    tenant, actor, client = setup_tenant()
    old = role(tenant, "old-position", ["catalog.view"])
    kept = role(tenant, "legacy-kept", ["orders.view"])
    replacement = role(tenant, "new-position", ["catalog.edit"])
    members = [user(tenant, f"member-{i}") for i in range(20)]
    for member in members:
        UserRole.objects.create(tenant=tenant, user=member, role=old, source="position")
        UserRole.objects.create(tenant=tenant, user=member, role=kept, source="legacy")
    response = preview(client, [u.pk for u in members], [replacement.code])
    assert response.status_code == 200
    changes = response.json()["data"]["changes"]
    assert len(changes) == 20
    assert all(row["added"] == ["catalog.edit"] and row["removed"] == ["catalog.view"] for row in changes)
    assert all(UserRole.objects.filter(user_id=row["user_id"], role=kept).exists() for row in changes)
    first = apply(client, response.json()["data"]["preview_token"])
    assert first.status_code == 200
    assert PermissionChange.objects.filter(tenant=tenant, operation="transfer").count() == 1
    assert UserRole.objects.filter(tenant=tenant, role=kept, source="legacy").count() == 20
    second = apply(client, response.json()["data"]["preview_token"])
    assert second.status_code == 200 and second.json()["data"].get("replayed") is True
    assert PermissionChange.objects.filter(tenant=tenant).count() == 1


@pytest.mark.parametrize("mutation", ["binding", "role"])
def test_preview_rejects_concurrent_target_or_role_change_without_member_mutation(mutation):
    tenant, actor, client = setup_tenant(f"stale-{mutation}")
    member = user(tenant, "target")
    target_role = role(tenant, "target-role", ["catalog.view"])
    response = preview(client, [member.pk], [target_role.code])
    assert response.status_code == 200
    if mutation == "binding":
        extra = role(tenant, "extra", ["orders.view"])
        UserRole.objects.create(tenant=tenant, user=member, role=extra, source="legacy")
    else:
        permission, _ = Permission.objects.get_or_create(code="catalog.edit", defaults={"name": "edit", "module": "catalog", "action": "edit"})
        target_role.permissions.add(permission)
    result = apply(client, response.json()["data"]["preview_token"])
    assert result.status_code == 409
    assert not UserRole.objects.filter(user=member, role=target_role).exists()
    assert PermissionChange.objects.filter(tenant=tenant).count() == 0


def test_batch_rejects_foreign_tenant_target_and_role():
    tenant, actor, client = setup_tenant("foreign-a")
    foreign, _, _ = setup_tenant("foreign-b")
    member = user(foreign, "foreign-target")
    foreign_role = role(foreign, "foreign-role")
    assert preview(client, [member.pk], []).status_code in (403, 404)
    local_member = user(tenant, "local-target")
    response = preview(client, [local_member.pk], [foreign_role.code])
    assert response.status_code in (403, 404)
    assert not UserRole.objects.filter(user=local_member).exists()


def test_resource_policy_rejects_empty_unsupported_and_foreign_dimension():
    tenant, _, _ = setup_tenant("policy-validation")
    foreign, _, _ = setup_tenant("policy-foreign")
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="W1", name="Warehouse", country_code="US",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY)
    other = PlatformMaster.objects.create(tenant=foreign, code="P1", name="Platform")
    target_role = role(tenant, "scoped")
    with pytest.raises(Exception):
        RoleResourcePolicy.objects.create(tenant=tenant, role=target_role, resource_code="warehouse_authorizations", scope_type="custom", config={})
    with pytest.raises(Exception):
        RoleResourcePolicy.objects.create(tenant=tenant, role=target_role, resource_code="warehouse_authorizations", scope_type="custom", config={"platform_ids": [1]})
    with pytest.raises(Exception):
        RoleResourcePolicy.objects.create(tenant=tenant, role=target_role, resource_code="masterdata.platforms", scope_type="custom", config={"platform_ids": [other.pk]})
    assert warehouse.pk > 0


def test_offboard_revokes_old_access_refresh_and_all_bindings_but_keeps_shared_role():
    from rest_framework_simplejwt.tokens import RefreshToken
    tenant, actor, client = setup_tenant("offboard")
    member = user(tenant, "departing")
    survivor = user(tenant, "survivor")
    shared = role(tenant, "shared", ["catalog.view"])
    UserRole.objects.create(tenant=tenant, user=member, role=shared, source="legacy")
    UserRole.objects.create(tenant=tenant, user=survivor, role=shared, source="legacy")
    dept = Department.objects.create(tenant=tenant, name="Ops")
    membership = OrgMembership.objects.create(tenant=tenant, user=member, department=dept)
    UserRole.objects.create(tenant=tenant, user=member, role=shared, membership=membership, context_key=f"department:{dept.pk}", source="position")
    refresh = RefreshToken.for_user(member)
    access = str(refresh.access_token)
    response = preview(client, [member.pk], [], operation="offboard")
    assert response.status_code == 200
    assert apply(client, response.json()["data"]["preview_token"]).status_code == 200
    member.refresh_from_db()
    assert not member.is_active
    assert not UserRole.objects.filter(user=member, status="active").exists()
    assert not OrgMembership.objects.filter(user=member, status="active").exists()
    assert UserRole.objects.filter(user=survivor, role=shared, status="active").exists()
    auth = APIClient()
    auth.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert auth.get("/api/internal/auth/me/").status_code in (401, 403)
    revoked = client.post("/api/internal/auth/refresh/", {"refresh": str(refresh)}, format="json")
    assert revoked.status_code in (400, 401, 403)


def test_resource_specific_scopes_are_distinct_and_all_role_does_not_expand_grant():
    from apps.permissions.services import get_permission_data_scopes
    tenant, _, _ = setup_tenant("scope-intersection")
    member = user(tenant, "scoped-user")
    base = role(tenant, "base", ["integrations.warehouse.view"])
    override = role(tenant, "override", ["listings.product_detail.view"])
    ungranted = role(tenant, "ungranted-all")
    warehouses = [WarehouseMaster.objects.create(tenant=tenant, code=f"W{i}", name=f"Warehouse {i}", country_code="US",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY) for i in (2, 3, 4)]
    platforms = [PlatformMaster.objects.create(tenant=tenant, code=f"P{i}", name=f"Platform {i}") for i in (6, 7)]
    DataScope.objects.create(tenant=tenant, role=base, scope_type="custom", config={"warehouse_ids": [w.pk for w in warehouses]})
    DataScope.objects.create(tenant=tenant, role=override, scope_type="all", config={})
    RoleResourcePolicy.objects.create(tenant=tenant, role=base, resource_code="warehouse_authorizations", permission_code="integrations.warehouse.view", scope_type="custom", config={"warehouse_ids": [w.pk for w in warehouses]})
    RoleResourcePolicy.objects.create(tenant=tenant, role=override, resource_code="platform_product_details", permission_code="listings.product_detail.view", scope_type="custom", config={"platform_ids": [platforms[0].pk]})
    RoleResourcePolicy.objects.create(tenant=tenant, role=ungranted, resource_code="platform_product_details", scope_type="all", config={})
    for assigned in (base, override, ungranted):
        UserRole.objects.create(tenant=tenant, user=member, role=assigned)
    warehouse_scope = get_permission_data_scopes(member, "integrations.warehouse.view", resource_code="warehouse_authorizations")
    platform_scope = get_permission_data_scopes(member, "listings.product_detail.view", resource_code="platform_product_details")
    assert warehouse_scope and warehouse_scope[0]["config"]["warehouse_ids"] == [w.pk for w in warehouses]
    assert platform_scope and platform_scope[0]["config"]["platform_ids"] == [platforms[0].pk]
    assert not Permission.objects.filter(code="ungranted.permission").exists()


def test_product_detail_scopes_and_dimensions_use_and_within_role_or_across_roles():
    from apps.permissions.ui_p6_scopes import filter_platform_product_details

    tenant, _, _ = setup_tenant("scope-and-or")
    member = user(tenant, "scope-user")
    platform_a = PlatformMaster.objects.create(tenant=tenant, code="platform-a", name="Platform A", platform_type="tiktok")
    platform_b = PlatformMaster.objects.create(tenant=tenant, code="platform-b", name="Platform B", platform_type="shopee")
    store_a = StoreMaster.objects.create(tenant=tenant, platform=platform_a, code="store-a", name="Store A", country_code="US", currency="USD")
    store_b = StoreMaster.objects.create(tenant=tenant, platform=platform_b, code="store-b", name="Store B", country_code="SG", currency="SGD")
    code = "listings.product_detail.view"
    role_a = role(tenant, "pair-a", [code])
    role_b = role(tenant, "pair-b", [code])
    ungranted = role(tenant, "ungranted-all")
    # A specific operation policy must replace the wildcard for that role.
    RoleResourcePolicy.objects.create(tenant=tenant, role=role_a, resource_code="platform_product_details", scope_type="all", config={})
    RoleResourcePolicy.objects.create(tenant=tenant, role=role_a, resource_code="platform_product_details", permission_code=code,
        scope_type="custom", config={"platform_ids": [platform_a.pk], "store_ids": [store_a.pk]})
    RoleResourcePolicy.objects.create(tenant=tenant, role=role_b, resource_code="platform_product_details", permission_code=code,
        scope_type="custom", config={"platform_ids": [platform_b.pk], "store_ids": [store_b.pk]})
    # This ALL policy must have no effect because this role does not grant `code`.
    RoleResourcePolicy.objects.create(tenant=tenant, role=ungranted, resource_code="platform_product_details", scope_type="all", config={})
    for assigned in (role_a, role_b, ungranted):
        UserRole.objects.create(tenant=tenant, user=member, role=assigned)
    rows = []
    for suffix, platform, store in (("aa", platform_a, store_a), ("ab", platform_a, store_b),
                                    ("ba", platform_b, store_a), ("bb", platform_b, store_b)):
        rows.append(PlatformProductDetail(tenant=tenant, platform=platform, store=store,
            platform_variant_id=f"variant-{suffix}"))
    PlatformProductDetail.objects.bulk_create(rows)
    actual = filter_platform_product_details(member, PlatformProductDetail.objects.all(), code)
    assert set(actual.values_list("platform_variant_id", flat=True)) == {"variant-aa", "variant-bb"}


def test_membership_context_isolated_expiry_and_invalid_membership_header():
    tenant, _, client = setup_tenant("membership-context")
    member = user(tenant, "contextual")
    can_manage = role(tenant, "membership-manage", ["catalog.manage"])
    can_read = role(tenant, "membership-read", ["catalog.view"])
    dep_a = Department.objects.create(tenant=tenant, name="A")
    dep_b = Department.objects.create(tenant=tenant, name="B")
    a = OrgMembership.objects.create(tenant=tenant, user=member, department=dep_a)
    b = OrgMembership.objects.create(tenant=tenant, user=member, department=dep_b)
    UserRole.objects.create(tenant=tenant, user=member, role=can_manage, membership=a, context_key=f"department:{dep_a.pk}", source="position")
    UserRole.objects.create(tenant=tenant, user=member, role=can_read, membership=b, context_key=f"department:{dep_b.pk}", source="position")
    from apps.permissions.services import check_user_permission
    member._active_membership_id = a.pk
    assert check_user_permission(member, "catalog.manage")
    member._active_membership_id = b.pk
    assert not check_user_permission(member, "catalog.manage") and check_user_permission(member, "catalog.view")
    member.__dict__.pop("_active_membership_id", None)
    assert not check_user_permission(member, "catalog.manage")
    expired = UserRole.objects.get(user=member, membership=a)
    expired.valid_until = timezone.now() - timedelta(seconds=1)
    expired.save(update_fields=["valid_until"])
    member._active_membership_id = a.pk
    assert not check_user_permission(member, "catalog.manage")
    from rest_framework_simplejwt.tokens import RefreshToken
    client.force_authenticate(user=None)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(member).access_token}")
    response = client.get("/api/internal/auth/me/", HTTP_X_ORG_MEMBERSHIP="999999")
    assert response.status_code in (400, 401, 403)


def test_me_authorization_version_matches_endpoint_and_changes_with_grants():
    tenant, _, client = setup_tenant("auth-version")
    member = user(tenant, "versioned")
    client.force_authenticate(member)
    me = client.get("/api/internal/auth/me/", {"include_modules": "1"})
    version = client.get("/api/internal/auth/authorization-version/")
    assert me.status_code == version.status_code == 200
    assert me.json()["data"]["authorization_version"] == version.json()["data"]["authorization_version"]
    prior = version.json()["data"]["authorization_version"]
    grant = role(tenant, "new-grant", ["catalog.view"])
    UserRole.objects.create(tenant=tenant, user=member, role=grant)
    after = client.get("/api/internal/auth/authorization-version/")
    assert after.json()["data"]["authorization_version"] != prior
