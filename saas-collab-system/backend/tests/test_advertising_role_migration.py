import importlib.util
from pathlib import Path

import pytest

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, PermissionChange, Role, UserRole
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

