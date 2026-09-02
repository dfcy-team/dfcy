import csv
import io

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.audit.services import write_operation_log
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def create_user(tenant, username):
    return CustomUser.objects.create_user(
        username=username,
        password="not-a-real-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )


def grant(user, *codes, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    role = Role.objects.create(tenant=user.tenant, code=f"role-{user.username}", name=user.username)
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "audit", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=scope_config or {})
    return role


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_operation_log_collection_requires_authentication():
    response = APIClient().get("/api/internal/audit/operation-logs/")

    assert response.status_code == 401


def test_operation_logs_are_tenant_and_scope_filtered_and_details_are_redacted():
    tenant = Tenant.objects.create(name="Tenant A", code="audit-tenant-a")
    other_tenant = Tenant.objects.create(name="Tenant B", code="audit-tenant-b")
    viewer = create_user(tenant, "audit-viewer")
    actor = create_user(tenant, "audit-actor")
    other_actor = create_user(other_tenant, "audit-other")
    grant(viewer, "audit.operation_logs.view", "audit.operation_logs.export")
    visible = write_operation_log(
        tenant=tenant,
        user=actor,
        module="system",
        action="user_update",
        object_type="user",
        object_id=actor.pk,
        before_data={"full_name": "Before", "password": "before-secret", "nested": {"token": "before-token"}},
        after_data={"full_name": "After", "api_key": "after-secret", "nested": {"safe": "value"}},
    )
    write_operation_log(tenant=other_tenant, user=other_actor, module="foreign", action="hidden")

    client = client_for(viewer)
    response = client.get("/api/internal/audit/operation-logs/", {"module": "system", "page_size": 10})

    assert response.status_code == 200
    assert response.data["success"] is True
    rows = response.data["data"]["results"]
    assert [row["id"] for row in rows] == [visible.pk]
    assert "before_data" not in rows[0]
    assert "after_data" not in rows[0]
    assert rows[0]["operator"] == actor.username

    detail = client.get(f"/api/internal/audit/operation-logs/{visible.pk}/")
    assert detail.status_code == 200
    detail_payload = detail.data["data"]
    assert detail_payload["before_data"]["full_name"] == "Before"
    assert detail_payload["before_data"]["password"] == "[REDACTED]"
    assert detail_payload["before_data"]["nested"]["token"] == "[REDACTED]"
    assert detail_payload["after_data"]["api_key"] == "[REDACTED]"
    assert "before-secret" not in str(detail_payload)
    assert "after-secret" not in str(detail_payload)

    export = client.get("/api/internal/audit/operation-logs/export/", {"module": "system"})
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    assert "attachment" in export["Content-Disposition"]
    assert "before-secret" not in export.content.decode("utf-8")
    assert "after-secret" not in export.content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(export.content.decode("utf-8"))))
    assert rows[0][1:5] == ["操作人", "操作人ID", "模块", "动作"]
    assert rows[1][1] == actor.username


def test_operation_log_own_scope_and_export_permission_are_enforced():
    tenant = Tenant.objects.create(name="Tenant", code="audit-own-scope")
    viewer = create_user(tenant, "own-viewer")
    actor = create_user(tenant, "own-actor")
    grant(viewer, "audit.operation_logs.view", scope_type=DataScope.ScopeType.OWN)
    own_log = write_operation_log(tenant=tenant, user=viewer, module="system", action="own")
    other_log = write_operation_log(tenant=tenant, user=actor, module="system", action="other")

    client = client_for(viewer)
    response = client.get("/api/internal/audit/operation-logs/")
    assert response.status_code == 200
    assert [row["id"] for row in response.data["data"]["results"]] == [own_log.pk]
    assert client.get(f"/api/internal/audit/operation-logs/{other_log.pk}/").status_code == 404
    assert client.get("/api/internal/audit/operation-logs/export/").status_code == 403


def test_operation_log_custom_scope_filters_dimensions_and_rejects_unknown_query_fields():
    tenant = Tenant.objects.create(name="Tenant", code="audit-custom-scope")
    viewer = create_user(tenant, "custom-viewer")
    grant(
        viewer,
        "audit.operation_logs.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"modules": ["allowed"]},
    )
    allowed = write_operation_log(tenant=tenant, user=viewer, module="allowed", action="view")
    write_operation_log(tenant=tenant, user=viewer, module="blocked", action="view")

    client = client_for(viewer)
    response = client.get("/api/internal/audit/operation-logs/", {"action": "view"})
    assert response.status_code == 200
    assert [row["id"] for row in response.data["data"]["results"]] == [allowed.pk]
    assert client.get("/api/internal/audit/operation-logs/", {"unexpected": "value"}).status_code == 400


def test_operation_log_custom_role_scope_filters_audited_objects():
    tenant = Tenant.objects.create(name="Tenant", code="audit-role-scope")
    viewer = create_user(tenant, "role-scope-viewer")
    target_role = Role.objects.create(tenant=tenant, code="target-role", name="Target role")
    other_role = Role.objects.create(tenant=tenant, code="other-role", name="Other role")
    grant(
        viewer,
        "audit.operation_logs.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"role_ids": [target_role.pk]},
    )
    allowed = write_operation_log(
        tenant=tenant,
        user=viewer,
        module="system",
        action="role_update",
        object_type="role",
        object_id=target_role.pk,
    )
    write_operation_log(
        tenant=tenant,
        user=viewer,
        module="system",
        action="role_update",
        object_type="role",
        object_id=other_role.pk,
    )

    response = client_for(viewer).get("/api/internal/audit/operation-logs/")

    assert response.status_code == 200
    assert [row["id"] for row in response.data["data"]["results"]] == [allowed.pk]


def test_operation_log_malformed_scope_and_cross_tenant_operator_fail_closed():
    tenant = Tenant.objects.create(name="Tenant", code="audit-fail-closed")
    other_tenant = Tenant.objects.create(name="Other", code="audit-fail-closed-other")
    viewer = create_user(tenant, "fail-closed-viewer")
    foreign_actor = create_user(other_tenant, "foreign-actor")
    grant(
        viewer,
        "audit.operation_logs.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"department_ids": ["not-an-integer"], "modules": ["system"]},
    )
    write_operation_log(
        tenant=tenant,
        user=foreign_actor,
        module="system",
        action="foreign_actor",
    )

    response = client_for(viewer).get("/api/internal/audit/operation-logs/")

    assert response.status_code == 200
    assert response.data["data"]["results"] == []


def test_operation_log_write_path_redacts_and_bounds_snapshots():
    tenant = Tenant.objects.create(name="Tenant", code="audit-write-boundary")
    viewer = create_user(tenant, "write-boundary-viewer")
    log = write_operation_log(
        tenant=tenant,
        user=viewer,
        module="audit",
        action="write",
        after_data={
            "credential": "raw-secret",
            "jwt": "eyJaaaaaaaaaaaa.eyJbbbbbbbbbbbb.cccccccccccc",
            "authorization_id": 42,
            "authorization": "Bearer sensitive-value",
            "safe": "x" * 5000,
        },
        user_agent="u" * 3000,
    )

    log.refresh_from_db()

    assert log.after_data["credential"] == "[REDACTED]"
    assert log.after_data["jwt"] == "[REDACTED]"
    assert log.after_data["authorization_id"] == 42
    assert log.after_data["authorization"] == "[REDACTED]"
    assert len(log.after_data["safe"]) == 4096
    assert len(log.user_agent) == 2048


def test_operation_log_export_reports_cap_and_emits_excel_safe_utf8():
    tenant = Tenant.objects.create(name="Tenant", code="audit-export-cap")
    viewer = create_user(tenant, "export-cap-viewer")
    grant(viewer, "audit.operation_logs.view", "audit.operation_logs.export")
    write_operation_log(tenant=tenant, user=viewer, module="system", action="first")
    write_operation_log(tenant=tenant, user=viewer, module="system", action="second")

    response = client_for(viewer).get("/api/internal/audit/operation-logs/export/", {"limit": 1})

    assert response.status_code == 200
    assert response.content.startswith("\ufeff".encode("utf-8"))
    assert response["X-Audit-Export-Count"] == "2"
    assert response["X-Audit-Export-Limit"] == "1"
    assert response["X-Audit-Export-Truncated"] == "true"
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 2


def test_operation_log_query_text_is_bounded():
    tenant = Tenant.objects.create(name="Tenant", code="audit-query-bound")
    viewer = create_user(tenant, "query-bound-viewer")
    grant(viewer, "audit.operation_logs.view")

    response = client_for(viewer).get(
        "/api/internal/audit/operation-logs/",
        {"search": "x" * 201},
    )

    assert response.status_code == 400
