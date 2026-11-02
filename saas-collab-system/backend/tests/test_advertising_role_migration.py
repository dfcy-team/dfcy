import importlib.util
from pathlib import Path

import pytest

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, PermissionChange, Role, RoleResourcePolicy, UserRole
from apps.tenants.models import Tenant

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge_shopee_ad_report_roles.py"
spec = importlib.util.spec_from_file_location("merge_ads_roles", SCRIPT)
merge_ads_roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_ads_roles)


@pytest.fixture
def role_migration_fixture(db):
    tenant = Tenant.objects.create(name="Ads role migration", code="ads-role-migration")
    actor = CustomUser.objects.create_user(username="migration-admin", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL, is_superuser=True)
    permissions = [Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "reports", "action": "view"})[0]
        for code in ("reports.view", "analytics.view")]
    target = Role.objects.create(tenant=tenant, code="operations-Shopee", name="Operations Shopee")
    target.permissions.add(*permissions)
    DataScope.objects.create(tenant=tenant, role=target, scope_type="custom", config={"warehouse_ids": [1]})
    users = []
    for username in ("lanx", "zhanzq"):
        user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
        users.append(user)
        UserRole.objects.create(tenant=tenant, user=user, role=target)
        personal = Role.objects.create(tenant=tenant, code=f"feishu-ads-report-{username}", name=username)
        UserRole.objects.create(tenant=tenant, user=user, role=personal)
        # A mixed scope without store_ids does not grant store access.
        DataScope.objects.create(tenant=tenant, role=personal, scope_type="custom", config={"warehouse_ids": [1]})
    return tenant, actor, users


@pytest.mark.django_db
def test_migration_preview_apply_restore_and_backup_no_overwrite(role_migration_fixture, tmp_path):
    tenant, actor, users = role_migration_fixture
    backup = tmp_path / "role-backup.json"
    before = list(UserRole.objects.filter(user__in=users).values_list("id", "status"))
    preview = merge_ads_roles.run("preview", tenant.pk)
    assert preview["status"] == "preview"
    assert not backup.exists()
    assert list(UserRole.objects.filter(user__in=users).values_list("id", "status")) == before

    applied = merge_ads_roles.run("apply", tenant.pk, actor.pk, backup)
    assert applied["status"] == "apply" and backup.exists()
    assert UserRole.objects.filter(user__in=users, role__code__startswith="feishu-ads-report-", status="inactive").count() == 2
    assert PermissionChange.objects.filter(tenant=tenant, operation="ad_roles_merge").exists()

    merge_ads_roles.run("restore", tenant.pk, actor.pk, backup)
    assert UserRole.objects.filter(user__in=users, role__code__startswith="feishu-ads-report-", status="active").count() == 2
    assert PermissionChange.objects.filter(tenant=tenant, operation="ad_roles_restore").exists()

    with pytest.raises(FileExistsError):
        merge_ads_roles.run("apply", tenant.pk, actor.pk, backup)
    assert UserRole.objects.filter(user__in=users, role__code__startswith="feishu-ads-report-", status="active").count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["permission", "resource_scope"])
def test_migration_refuses_uncovered_authorization(role_migration_fixture, tmp_path, kind):
    tenant, actor, users = role_migration_fixture
    user = users[0]
    personal = Role.objects.get(tenant=tenant, code=f"feishu-ads-report-{user.username}")
    if kind == "permission":
        extra = Permission.objects.create(code="reports.private_export", name="Private export",
            module="reports", action="export")
        personal.permissions.add(extra)
    else:
        from apps.masterdata.models import PlatformMaster, StoreMaster
        platform = PlatformMaster.objects.create(tenant=tenant, code="guard-shop", name="Shop", platform_type="shopee")
        store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="guard-store", name="Guard store", country_code="PH", currency="PHP")
        RoleResourcePolicy.objects.create(tenant=tenant, role=personal, resource_code="reports.sales",
            permission_code="*", scope_type="custom", config={"store_ids": [store.pk]})

    backup = tmp_path / f"{kind}-backup.json"
    preview = merge_ads_roles.run("preview", tenant.pk)
    diff = preview["users"][0]["authorization_diff"]
    assert diff["permissions"] if kind == "permission" else diff["resource_policies"]
    before = list(UserRole.objects.filter(user__in=users).values_list("id", "status"))
    with pytest.raises(ValueError, match="uncovered permissions or resource scopes"):
        merge_ads_roles.run("apply", tenant.pk, actor.pk, backup)
    assert not backup.exists()
    assert list(UserRole.objects.filter(user__in=users).values_list("id", "status")) == before


@pytest.mark.django_db
def test_migration_refuses_coverage_stitched_across_roles(role_migration_fixture, tmp_path):
    tenant, actor, users = role_migration_fixture
    user = users[0]
    personal = Role.objects.get(tenant=tenant, code=f"feishu-ads-report-{user.username}")
    finance, _ = Permission.objects.get_or_create(code="finance.view", defaults={"name": "Finance", "module": "finance", "action": "view"})
    personal.permissions.add(finance)

    permission_role = Role.objects.create(tenant=tenant, code="finance-with-other-scope", name="Finance scope B")
    permission_role.permissions.add(finance)
    UserRole.objects.create(tenant=tenant, user=user, role=permission_role)
    DataScope.objects.create(tenant=tenant, role=permission_role, scope_type="custom", config={"store_ids": [2]})

    scope_role = Role.objects.create(tenant=tenant, code="scope-without-finance", name="Scope A only")
    UserRole.objects.create(tenant=tenant, user=user, role=scope_role)
    DataScope.objects.create(tenant=tenant, role=scope_role, scope_type="custom", config={"warehouse_ids": [1]})

    preview = merge_ads_roles.run("preview", tenant.pk)
    diff = preview["users"][0]["authorization_diff"]
    assert not diff["permissions"] and not diff["data_scopes"]
    assert diff["coverage_proof"] == {"proven": False, "covering_role_ids": []}
    with pytest.raises(ValueError, match="uncovered permissions or resource scopes"):
        merge_ads_roles.run("apply", tenant.pk, actor.pk, tmp_path / "stitched-backup.json")

