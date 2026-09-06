import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser, InternalUserProfile
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department, Tenant


pytestmark = pytest.mark.django_db


def create_internal(tenant, username, *, department=None):
    user = CustomUser.objects.create_user(
        username=username,
        password="test-password-123",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    profile = InternalUserProfile.objects.create(
        tenant=tenant,
        user=user,
        department=department,
    )
    return user, profile


def grant(user, *permission_codes, scope_type=DataScope.ScopeType.ALL):
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"{user.username}-{Role.objects.filter(tenant=user.tenant).count()}",
        code=f"{user.username}-scope-{Role.objects.filter(tenant=user.tenant).count()}",
    )
    role.permissions.set(Permission.objects.filter(code__in=permission_codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config={})
    return role


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def tree_items(response):
    return response.data["data"]["items"]


def flatten(nodes):
    result = []
    for node in nodes:
        result.append(node)
        result.extend(flatten(node.get("children") or []))
    return result


def test_department_tree_returns_tenant_forest_and_filtered_counts():
    tenant = Tenant.objects.create(name="Tree tenant", code="tree-tenant")
    other_tenant = Tenant.objects.create(name="Other tree tenant", code="other-tree-tenant")
    root = Department.objects.create(tenant=tenant, name="Root")
    child = Department.objects.create(tenant=tenant, name="Child", parent=root)
    Department.objects.create(tenant=other_tenant, name="Foreign")

    viewer, _ = create_internal(tenant, "tree-viewer")
    root_user, _ = create_internal(tenant, "root-user", department=root)
    child_user, _ = create_internal(tenant, "child-user", department=child)
    _, secondary_profile = create_internal(tenant, "secondary-user")
    secondary_profile.departments.set([root])
    grant(viewer, "system.organization.view", "system.users.view")

    response = client_for(viewer).get("/api/internal/system/departments/tree/")

    assert response.status_code == 200
    roots = tree_items(response)
    assert {item["name"] for item in roots} == {"Root"}
    root_node = roots[0]
    assert root_node["parent_id"] is None
    assert root_node["direct_user_count"] == 2
    assert root_node["descendant_user_count"] == 1
    assert root_node["children"][0]["id"] == child.pk
    assert root_node["children"][0]["direct_user_count"] == 1
    assert "parent_name" not in root_node
    assert all(item["tenant_id"] if "tenant_id" in item else True for item in flatten(roots))
    assert "Foreign" not in {item["name"] for item in flatten(roots)}
    assert root_user.pk != child_user.pk


def test_department_tree_hides_counts_without_users_view():
    tenant = Tenant.objects.create(name="Tree no-count tenant", code="tree-no-count")
    root = Department.objects.create(tenant=tenant, name="Root")
    viewer, _ = create_internal(tenant, "org-only-viewer")
    create_internal(tenant, "hidden-count-user", department=root)
    grant(viewer, "system.organization.view")

    response = client_for(viewer).get("/api/internal/system/departments/tree/")

    assert response.status_code == 200
    node = tree_items(response)[0]
    assert node["direct_user_count"] is None
    assert node["descendant_user_count"] is None


def test_department_tree_breaks_legacy_parent_cycle_and_hidden_parent_is_root():
    tenant = Tenant.objects.create(name="Tree cycle tenant", code="tree-cycle")
    first = Department.objects.create(tenant=tenant, name="First")
    second = Department.objects.create(tenant=tenant, name="Second", parent=first)
    Department.objects.filter(pk=first.pk).update(parent=second)
    viewer, _ = create_internal(tenant, "cycle-viewer")
    grant(viewer, "system.organization.view")

    response = client_for(viewer).get("/api/internal/system/departments/tree/")

    assert response.status_code == 200
    assert len(tree_items(response)) == 2
    assert all(item["parent_id"] is None for item in tree_items(response))

    scoped_tenant = Tenant.objects.create(name="Tree hidden parent tenant", code="tree-hidden-parent")
    hidden_root = Department.objects.create(tenant=scoped_tenant, name="Hidden root")
    visible_child = Department.objects.create(tenant=scoped_tenant, name="Visible child", parent=hidden_root)
    scoped_viewer, _ = create_internal(scoped_tenant, "child-viewer", department=visible_child)
    grant(scoped_viewer, "system.organization.view", scope_type=DataScope.ScopeType.DEPARTMENT)

    scoped_response = client_for(scoped_viewer).get("/api/internal/system/departments/tree/")

    assert scoped_response.status_code == 200
    scoped_node = tree_items(scoped_response)[0]
    assert scoped_node["id"] == visible_child.pk
    assert scoped_node["parent_id"] is None
    assert "parent_name" not in scoped_node
    assert scoped_node["name"] != hidden_root.name


def test_department_scope_is_direct_but_department_tree_scope_includes_primary_descendants():
    tenant = Tenant.objects.create(name="Tree scope tenant", code="tree-scope")
    root = Department.objects.create(tenant=tenant, name="Root")
    child = Department.objects.create(tenant=tenant, name="Child", parent=root)
    direct_viewer, _ = create_internal(tenant, "direct-viewer", department=root)
    tree_viewer, _ = create_internal(tenant, "tree-viewer", department=root)
    create_internal(tenant, "root-member", department=root)
    create_internal(tenant, "child-member", department=child)
    grant(direct_viewer, "system.users.view", scope_type=DataScope.ScopeType.DEPARTMENT)
    grant(tree_viewer, "system.users.view", scope_type=DataScope.ScopeType.DEPARTMENT_TREE)

    direct_response = client_for(direct_viewer).get("/api/internal/system/users/")
    tree_response = client_for(tree_viewer).get("/api/internal/system/users/")

    direct_names = {item["username"] for item in direct_response.data["data"]["results"]}
    tree_names = {item["username"] for item in tree_response.data["data"]["results"]}
    assert "child-member" not in direct_names
    assert "child-member" in tree_names


def test_user_department_filters_include_descendants_secondary_and_unassigned():
    tenant = Tenant.objects.create(name="User filter tenant", code="user-filter")
    root = Department.objects.create(tenant=tenant, name="Root")
    child = Department.objects.create(tenant=tenant, name="Child", parent=root)
    viewer, viewer_profile = create_internal(tenant, "filter-viewer", department=root)
    root_user, _ = create_internal(tenant, "root-member", department=root)
    child_user, _ = create_internal(tenant, "child-member", department=child)
    secondary_user, secondary_profile = create_internal(tenant, "secondary-member")
    secondary_profile.departments.set([child])
    unassigned, _ = create_internal(tenant, "unassigned-member")
    grant(viewer, "system.organization.view", "system.users.view")
    client = client_for(viewer)

    direct = client.get(
        f"/api/internal/system/users/?department_id={root.pk}&include_descendants=false"
    )
    subtree = client.get(
        f"/api/internal/system/users/?department_id={root.pk}&include_descendants=true"
    )
    unassigned_response = client.get("/api/internal/system/users/?unassigned=true")

    assert direct.status_code == 200
    assert {item["username"] for item in direct.data["data"]["results"]} == {
        "root-member",
        "filter-viewer",
    }
    assert subtree.status_code == 200
    assert {item["username"] for item in subtree.data["data"]["results"]} == {
        "root-member",
        "child-member",
        "secondary-member",
        "filter-viewer",
    }
    assert unassigned_response.status_code == 200
    assert {item["username"] for item in unassigned_response.data["data"]["results"]} == {
        "unassigned-member",
    }
    assert root_user.pk != child_user.pk
    assert unassigned.pk != viewer.pk


def test_user_department_filter_rejects_foreign_or_invisible_department():
    tenant = Tenant.objects.create(name="User filter tenant A", code="user-filter-a")
    other = Tenant.objects.create(name="User filter tenant B", code="user-filter-b")
    foreign_department = Department.objects.create(tenant=other, name="Foreign")
    viewer, _ = create_internal(tenant, "filter-boundary-viewer")
    grant(viewer, "system.users.view", "system.organization.view")

    response = client_for(viewer).get(
        f"/api/internal/system/users/?department_id={foreign_department.pk}"
    )

    assert response.status_code == 404


def test_user_department_patch_enforces_management_scope_returns_ids_and_audits_change():
    tenant = Tenant.objects.create(name="User move tenant", code="user-move")
    root = Department.objects.create(tenant=tenant, name="Root")
    child = Department.objects.create(tenant=tenant, name="Child", parent=root)
    hidden = Department.objects.create(tenant=tenant, name="Hidden")
    manager, _ = create_internal(tenant, "move-manager", department=root)
    target, _ = create_internal(tenant, "move-target", department=root)
    grant(manager, "system.users.view", "system.users.manage", scope_type=DataScope.ScopeType.DEPARTMENT_TREE)
    client = client_for(manager)

    moved = client.patch(
        f"/api/internal/system/users/{target.pk}/",
        {"department_id": child.pk, "department_ids": [root.pk, child.pk]},
        format="json",
    )

    assert moved.status_code == 200
    target.refresh_from_db()
    assert target.internal_profile.department_id == child.pk
    assert set(target.internal_profile.departments.values_list("id", flat=True)) == {root.pk, child.pk}
    payload = moved.data["data"]
    assert payload["department_id"] == child.pk
    assert set(payload["department_ids"]) == {root.pk, child.pk}
    audit = OperationLog.objects.get(tenant=tenant, action="user_profile_update", object_id=str(target.pk))
    assert audit.before_data["department_id"] == root.pk
    assert audit.after_data["department_id"] == child.pk

    denied = client.patch(
        f"/api/internal/system/users/{target.pk}/",
        {"department_id": hidden.pk, "department_ids": [hidden.pk]},
        format="json",
    )
    assert denied.status_code == 403
    target.refresh_from_db()
    assert target.internal_profile.department_id == child.pk
