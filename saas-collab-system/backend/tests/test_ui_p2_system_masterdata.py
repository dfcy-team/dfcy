import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, InternalUserProfile
from apps.audit.models import OperationLog
from apps.integrations.models import PlatformIntegrationConfig
from apps.masterdata.models import PlatformMaster, StatusChoices, StoreMaster, SupplierMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.suppliers.models import SupplierTask
from apps.tenants.models import Department, Tenant


pytestmark = pytest.mark.django_db


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL, **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=user_type,
        **kwargs,
    )


def grant(user, *permission_codes, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"role-{user.username}", name=f"Role {user.username}")
    for code in permission_codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".")[0], "action": code.split(".", 1)[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )
    return role


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_system_user_directory_is_tenant_filtered_and_masked():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p2-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p2-b")
    viewer = create_user(tenant, "directory-viewer")
    create_user(tenant, "visible-user", email="visible@example.com", phone="13800138000")
    create_user(other, "hidden-user", email="hidden@example.com", phone="13900139000")
    grant(viewer, "system.users.view")

    response = client_for(viewer).get("/api/internal/system/users/")

    assert response.status_code == 200
    assert response.data["success"] is True
    usernames = {item["username"] for item in response.data["data"]["results"]}
    assert usernames == {"directory-viewer", "visible-user"}
    visible = next(item for item in response.data["data"]["results"] if item["username"] == "visible-user")
    assert visible["email_masked"] == "v***@example.com"
    assert visible["phone_masked"] == "***8000"
    assert "email" not in visible and "phone" not in visible


def test_system_user_directory_enforces_permission_bound_own_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-own-scope")
    viewer = create_user(tenant, "scope-viewer")
    create_user(tenant, "other-user")
    grant(viewer, "system.users.view", scope_type=DataScope.ScopeType.OWN)

    response = client_for(viewer).get("/api/internal/system/users/")

    assert response.status_code == 200
    assert [item["username"] for item in response.data["data"]["results"]] == ["scope-viewer"]


def test_declared_permission_without_data_scope_is_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-missing-scope")
    viewer = create_user(tenant, "missing-scope-viewer")
    permission, _ = Permission.objects.get_or_create(
        code="system.users.view",
        defaults={"name": "View users", "module": "system", "action": "users.view"},
    )
    role = Role.objects.create(tenant=tenant, name="Missing scope", code="missing-scope")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=viewer, role=role)

    response = client_for(viewer).get("/api/internal/system/users/")

    assert response.status_code == 403


def test_department_and_role_queries_enforce_department_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-department-scope")
    department = Department.objects.create(tenant=tenant, name="Allowed department")
    other_department = Department.objects.create(tenant=tenant, name="Other department")
    viewer = create_user(tenant, "department-viewer")
    coworker = create_user(tenant, "department-coworker")
    outsider = create_user(tenant, "department-outsider")
    InternalUserProfile.objects.create(tenant=tenant, user=viewer, department=department)
    InternalUserProfile.objects.create(tenant=tenant, user=coworker, department=department)
    InternalUserProfile.objects.create(tenant=tenant, user=outsider, department=other_department)
    grant(
        viewer,
        "system.organization.view",
        "system.roles.view",
        scope_type=DataScope.ScopeType.DEPARTMENT,
    )
    allowed_role = Role.objects.create(tenant=tenant, name="Allowed role", code="allowed-role")
    blocked_role = Role.objects.create(tenant=tenant, name="Blocked role", code="blocked-role")
    UserRole.objects.create(tenant=tenant, user=coworker, role=allowed_role)
    UserRole.objects.create(tenant=tenant, user=outsider, role=blocked_role)
    client = client_for(viewer)

    departments = client.get("/api/internal/system/departments/").data["data"]["results"]
    assert [item["id"] for item in departments] == [department.pk]
    roles = client.get("/api/internal/system/roles/").data["data"]["results"]
    role_codes = {item["code"] for item in roles}
    assert "allowed-role" in role_codes
    assert "blocked-role" not in role_codes


def test_security_operations_requires_all_scope():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-security-scope")
    viewer = create_user(tenant, "scoped-security-viewer")
    grant(viewer, "security.operations.view", scope_type=DataScope.ScopeType.OWN)

    response = client_for(viewer).get("/api/internal/system/security-operations/")

    assert response.status_code == 403


def test_system_endpoints_reject_missing_permission_external_and_rpa():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-permission")
    plain_internal = create_user(tenant, "plain-internal")
    external = create_user(tenant, "external-user", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa-user", CustomUser.UserType.RPA)

    for user in (plain_internal, external, rpa):
        assert client_for(user).get("/api/internal/system/users/").status_code == 403
        assert client_for(user).get("/api/internal/master-data/platforms/").status_code == 403


def test_view_permissions_cannot_execute_system_or_master_data_writes():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-view-only")
    viewer = create_user(tenant, "view-only-user")
    grant(viewer, "system.users.view", "masterdata.view")
    client = client_for(viewer)

    assert client.get("/api/internal/system/users/").status_code == 200
    assert client.get("/api/internal/master-data/platforms/").status_code == 200
    assert client.post(
        "/api/internal/system/users/",
        {"username": "blocked-user", "initial_password": "not-a-real-password"},
        format="json",
    ).status_code == 403
    assert client.post(
        "/api/internal/master-data/platforms/",
        {"code": "blocked-platform", "name": "Blocked", "platform_type": "other"},
        format="json",
    ).status_code == 403


def test_department_uniqueness_and_cross_tenant_parent_are_enforced():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p2-department-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p2-department-b")
    manager = create_user(tenant, "org-manager")
    grant(manager, "system.organization.view", "system.organization.manage")
    client = client_for(manager)

    created = client.post("/api/internal/system/departments/", {"name": "Operations", "status": "active"}, format="json")
    assert created.status_code == 201
    duplicate = client.post("/api/internal/system/departments/", {"name": "Operations", "status": "active"}, format="json")
    assert duplicate.status_code == 400

    from apps.tenants.models import Department

    foreign_parent = Department.objects.create(tenant=other, name="Foreign")
    cross_tenant = client.post(
        "/api/internal/system/departments/",
        {"name": "Invalid child", "parent_id": foreign_parent.pk, "status": "active"},
        format="json",
    )
    assert cross_tenant.status_code == 400


def test_role_permission_and_data_scope_update_is_audited():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-role")
    manager = create_user(tenant, "role-manager")
    grant(manager, "system.roles.view", "system.roles.manage")
    target = Role.objects.create(tenant=tenant, name="Buyer", code="buyer")
    Permission.objects.get_or_create(
        code="masterdata.view",
        defaults={"name": "View master data", "module": "masterdata", "action": "view"},
    )

    response = client_for(manager).put(
        f"/api/internal/system/roles/{target.pk}/permissions/",
        {"permission_codes": ["masterdata.view"], "scope_type": "department", "scope_config": {"department_ids": [10]}},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["data"]["permission_codes"] == ["masterdata.view"]
    assert DataScope.objects.get(role=target).scope_type == DataScope.ScopeType.DEPARTMENT
    audit = OperationLog.objects.get(tenant=tenant, action="role_permissions_update", object_id=str(target.pk))
    assert audit.after_data["data_scopes"] == [
        {"scope_type": "department", "config": {"department_ids": [10]}}
    ]


def test_user_role_assignment_uses_users_manage_without_roles_view():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-role-assignment")
    manager = create_user(tenant, "user-role-manager")
    target = create_user(tenant, "role-target")
    grant(manager, "system.users.manage")
    assignable = Role.objects.create(tenant=tenant, name="Operator", code="operator")
    client = client_for(manager)

    options = client.get("/api/internal/system/user-role-options/?page=1&page_size=100")
    assigned = client.put(
        f"/api/internal/system/users/{target.pk}/roles/",
        {"role_codes": [assignable.code]},
        format="json",
    )

    assert options.status_code == 200
    assert assignable.code in {item["code"] for item in options.data["data"]["results"]}
    assert assigned.status_code == 200
    assert assigned.data["data"]["roles"] == [assignable.code]
    assert OperationLog.objects.filter(
        tenant=tenant,
        action="user_roles_update",
        object_id=str(target.pk),
    ).exists()


def test_user_role_assignment_enforces_target_and_assignable_role_scopes():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-role-assignment-scope")
    manager = create_user(tenant, "scoped-role-manager")
    allowed_target = create_user(tenant, "allowed-role-target")
    blocked_target = create_user(tenant, "blocked-role-target")
    allowed_role = Role.objects.create(tenant=tenant, name="Allowed role", code="allowed-role")
    blocked_role = Role.objects.create(tenant=tenant, name="Blocked role", code="blocked-role")
    grant(
        manager,
        "system.users.manage",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"user_ids": [allowed_target.pk], "role_ids": [allowed_role.pk]},
    )
    client = client_for(manager)

    options = client.get("/api/internal/system/user-role-options/")
    assert [item["code"] for item in options.data["data"]["results"]] == [allowed_role.code]
    assert client.put(
        f"/api/internal/system/users/{allowed_target.pk}/roles/",
        {"role_codes": [blocked_role.code]},
        format="json",
    ).status_code == 403
    assert client.put(
        f"/api/internal/system/users/{blocked_target.pk}/roles/",
        {"role_codes": [allowed_role.code]},
        format="json",
    ).status_code == 404
    assert client.put(
        f"/api/internal/system/users/{allowed_target.pk}/roles/",
        {"role_codes": [allowed_role.code]},
        format="json",
    ).status_code == 200


def test_role_collection_exposes_second_page_and_total_count():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-role-pagination")
    viewer = create_user(tenant, "role-pagination-viewer")
    grant(viewer, "system.roles.view")
    for index in range(25):
        Role.objects.create(tenant=tenant, name=f"Role {index:02d}", code=f"page-role-{index:02d}")

    response = client_for(viewer).get("/api/internal/system/roles/?page=2&page_size=20")

    assert response.status_code == 200
    assert response.data["data"]["count"] == 26
    assert len(response.data["data"]["results"]) == 6
    assert response.data["data"]["previous"] is not None
    assert response.data["data"]["next"] is None


def test_master_data_is_tenant_filtered_and_codes_are_unique_per_tenant():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p2-master-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p2-master-b")
    manager = create_user(tenant, "master-manager")
    grant(manager, "masterdata.view", "masterdata.manage")
    PlatformMaster.objects.create(tenant=other, code="demo-platform", name="Foreign", platform_type="other")
    client = client_for(manager)

    created = client.post(
        "/api/internal/master-data/platforms/",
        {"code": "demo-platform", "name": "Demo platform", "platform_type": "other"},
        format="json",
    )
    assert created.status_code == 201
    listed = client.get("/api/internal/master-data/platforms/")
    assert [item["code"] for item in listed.data["data"]["results"]] == ["demo-platform"]
    duplicate = client.post(
        "/api/internal/master-data/platforms/",
        {"code": "demo-platform", "name": "Duplicate", "platform_type": "other"},
        format="json",
    )
    assert duplicate.status_code == 400


def test_master_data_custom_scope_filters_list_detail_and_status_actions():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-master-scope")
    manager = create_user(tenant, "scoped-master-manager")
    allowed = PlatformMaster.objects.create(
        tenant=tenant, code="allowed-platform", name="Allowed", platform_type="other"
    )
    blocked = PlatformMaster.objects.create(
        tenant=tenant, code="blocked-platform", name="Blocked", platform_type="other"
    )
    grant(
        manager,
        "masterdata.view",
        "masterdata.manage",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"platform_ids": [allowed.pk]},
    )
    client = client_for(manager)

    listed = client.get("/api/internal/master-data/platforms/")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.data["data"]["results"]] == [allowed.pk]
    assert client.get(f"/api/internal/master-data/platforms/{blocked.pk}/").status_code == 404
    assert client.post(
        f"/api/internal/master-data/platforms/{blocked.pk}/status/",
        {"status": "inactive"},
        format="json",
    ).status_code == 404
    allowed_status = client.post(
        f"/api/internal/master-data/platforms/{allowed.pk}/status/",
        {"status": "inactive"},
        format="json",
    )
    assert allowed_status.status_code == 200
    assert client.post(
        "/api/internal/master-data/platforms/",
        {"code": "new-platform", "name": "New", "platform_type": "other"},
        format="json",
    ).status_code == 403


def test_store_rejects_platform_outside_tenant_scope():
    tenant = Tenant.objects.create(name="Tenant A", code="ui-p2-store-scope-a")
    other = Tenant.objects.create(name="Tenant B", code="ui-p2-store-scope-b")
    manager = create_user(tenant, "store-manager")
    grant(manager, "masterdata.view", "masterdata.manage")
    foreign_platform = PlatformMaster.objects.create(
        tenant=other, code="foreign-platform", name="Foreign", platform_type="other"
    )

    response = client_for(manager).post(
        "/api/internal/master-data/stores/",
        {
            "platform_id": foreign_platform.pk,
            "code": "invalid-store",
            "name": "Invalid store",
            "country_code": "SG",
            "currency": "SGD",
        },
        format="json",
    )

    assert response.status_code == 400


def test_platform_with_active_store_cannot_be_disabled():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-reference")
    manager = create_user(tenant, "reference-manager")
    grant(manager, "masterdata.view", "masterdata.manage")
    platform = PlatformMaster.objects.create(tenant=tenant, code="platform", name="Platform", platform_type="other")
    StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store",
        name="Store",
        country_code="SG",
        currency="SGD",
        status=StatusChoices.ACTIVE,
    )

    response = client_for(manager).post(
        f"/api/internal/master-data/platforms/{platform.pk}/status/",
        {"status": "inactive"},
        format="json",
    )

    assert response.status_code == 409
    platform.refresh_from_db()
    assert platform.status == StatusChoices.ACTIVE


def test_supplier_with_active_task_cannot_be_disabled():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-supplier-reference")
    manager = create_user(tenant, "supplier-reference-manager")
    grant(manager, "masterdata.view", "masterdata.manage")
    supplier = SupplierMaster.objects.create(tenant=tenant, code="supplier", name="Supplier")
    SupplierTask.objects.create(
        tenant=tenant,
        supplier_id=supplier.pk,
        task_no="demo-task",
        sku_code="demo-sku",
        production_quantity=10,
        status=SupplierTask.Status.IN_PROGRESS,
    )

    response = client_for(manager).post(
        f"/api/internal/master-data/suppliers/{supplier.pk}/status/",
        {"status": "inactive"},
        format="json",
    )

    assert response.status_code == 409
    supplier.refresh_from_db()
    assert supplier.status == StatusChoices.ACTIVE


def test_supplier_contacts_are_never_returned_in_plaintext():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-supplier")
    manager = create_user(tenant, "supplier-manager")
    grant(manager, "masterdata.view", "masterdata.manage")
    SupplierMaster.objects.create(
        tenant=tenant,
        code="supplier",
        name="Supplier",
        contact_alias="Contact A",
        contact_email="contact@example.com",
        contact_phone="13800138888",
    )

    item = client_for(manager).get("/api/internal/master-data/suppliers/").data["data"]["results"][0]
    assert item["contact_email_masked"] == "c***@example.com"
    assert item["contact_phone_masked"] == "***8888"
    assert "contact_email" not in item and "contact_phone" not in item


def test_security_operations_exposes_only_credential_metadata():
    tenant = Tenant.objects.create(name="Tenant", code="ui-p2-security")
    viewer = create_user(tenant, "security-viewer")
    grant(viewer, "security.operations.view")
    PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="other",
        account_alias="demo-alias",
        environment="sandbox",
        status="disabled",
        credential_ciphertext="not-a-real-secret-ciphertext",
        credential_key_version="demo-v1",
        credential_fingerprint="demo-fingerprint",
        created_by=viewer,
    )

    response = client_for(viewer).get("/api/internal/system/security-operations/")

    assert response.status_code == 200
    serialized = str(response.data)
    assert "demo-alias" in serialized and "demo-fingerprint" in serialized
    assert "not-a-real-secret-ciphertext" not in serialized
    assert response.data["data"]["credential_contract"] == "alias_fingerprint_reference_only"
