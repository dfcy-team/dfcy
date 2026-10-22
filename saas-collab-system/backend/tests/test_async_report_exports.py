from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.reports.async_exports import export_fingerprint, run_export
from apps.reports.models import ReportAnalysisJob, ReportExportRequest
from apps.tenants.models import Tenant


def _user(tenant, name):
    return CustomUser.objects.create_user(username=name, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def _grant(user, code, scope_type=DataScope.ScopeType.ALL, config=None):
    permission, _ = Permission.objects.get_or_create(
        code=code,
        defaults={"name": code, "module": code.split(".", 1)[0], "action": code.rsplit(".", 1)[-1]},
    )
    role = Role.objects.create(tenant=user.tenant, name=f"{code}-{user.pk}", code=f"{code}-{user.pk}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    return DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db(transaction=True)
def test_export_job_submission_deduplicates_and_does_not_build_on_http_request():
    tenant = Tenant.objects.create(name="Export jobs", code="async-export-jobs")
    user = _user(tenant, "async-exporter")
    _grant(user, "reports.view")
    _grant(user, "reports.export")
    _grant(user, "replenishment.view")
    payload = {"report_type": "replenishment", "filters": {}}

    with patch("apps.reports.async_exports.run_export.apply_async") as enqueue, patch(
        "apps.reports.async_exports.create_export_request"
    ) as build:
        first = _client(user).post("/api/report/export-jobs/", payload, format="json")
        second = _client(user).post("/api/report/export-jobs/", payload, format="json")

    assert first.status_code == second.status_code == 202
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert ReportAnalysisJob.objects.filter(config__kind="export").count() == 1
    enqueue.assert_called_once()
    build.assert_not_called()


@pytest.mark.django_db
def test_export_job_is_owner_scoped_cancelled_and_hidden_when_export_scope_changes():
    tenant = Tenant.objects.create(name="Export owners", code="async-export-owners")
    owner = _user(tenant, "async-owner")
    other = _user(tenant, "async-other")
    for user in (owner, other):
        _grant(user, "reports.view")
        _grant(user, "reports.export")
        _grant(user, "replenishment.view")
    with patch("apps.reports.async_exports.run_export.apply_async"):
        created = _client(owner).post("/api/report/export-jobs/", {"report_type": "replenishment"}, format="json")
    job_id = created.json()["data"]["id"]

    assert _client(other).get(f"/api/report/export-jobs/{job_id}/").status_code == 404
    cancelled = _client(owner).delete(f"/api/report/export-jobs/{job_id}/")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    next_created = _client(owner).post("/api/report/export-jobs/", {"report_type": "replenishment"}, format="json")
    next_id = next_created.json()["data"]["id"]
    export_scope = DataScope.objects.get(role__user_roles__user=owner, role__permissions__code="reports.export")
    export_scope.scope_type = DataScope.ScopeType.CUSTOM
    export_scope.config = {"report_types": ["finance_summary"]}
    export_scope.save(update_fields=["scope_type", "config"])
    stale = _client(owner).get(f"/api/report/export-jobs/{next_id}/")

    assert stale.status_code == 403


@pytest.mark.django_db
def test_export_worker_invokes_existing_service_and_stores_result():
    tenant = Tenant.objects.create(name="Export worker", code="async-export-worker")
    user = _user(tenant, "async-worker")
    _grant(user, "reports.view")
    _grant(user, "reports.export")
    _grant(user, "replenishment.view")
    config, fingerprint = export_fingerprint(user, "replenishment", {})
    from django.utils import timezone
    from datetime import timedelta

    job = ReportAnalysisJob.objects.create(
        tenant=tenant, requested_by=user, config=config, fingerprint=fingerprint,
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    run_export(job.pk)
    job.refresh_from_db()

    assert job.status == "completed"
    assert job.result["export"]["status"] == ReportExportRequest.Status.COMPLETED
    assert ReportExportRequest.objects.filter(requested_by=user).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("scope", [
    {"platform_ids": [1], "warehouse_ids": [3]},
    {"report_types": ["finance_summary"]},
])
def test_incompatible_or_excluded_export_scope_rejected_before_queue(scope):
    tenant = Tenant.objects.create(name="Invalid export scope", code="bad-export-scope")
    user = _user(tenant, "bad-exporter")
    _grant(user, "reports.view")
    _grant(user, "reports.export", DataScope.ScopeType.CUSTOM, scope)
    _grant(user, "replenishment.view")
    with patch("apps.reports.async_exports.run_export.apply_async") as enqueue:
        response = _client(user).post("/api/report/export-jobs/", {"report_type": "replenishment"}, format="json")
    assert response.status_code == 403
    assert not ReportAnalysisJob.objects.exists()
    enqueue.assert_not_called()
    if "warehouse_ids" in scope:
        assert "报表导出数据范围配置不兼容" in response.content.decode()


@pytest.mark.django_db
def test_worker_preserves_scope_configuration_error():
    tenant = Tenant.objects.create(name="Worker scope change", code="worker-scope-change")
    user = _user(tenant, "changed-exporter")
    _grant(user, "reports.view")
    scope = _grant(user, "reports.export")
    _grant(user, "replenishment.view")
    config, fingerprint = export_fingerprint(user, "replenishment", {})
    from django.utils import timezone
    from datetime import timedelta
    job = ReportAnalysisJob.objects.create(tenant=tenant, requested_by=user, config=config,
        fingerprint=fingerprint, expires_at=timezone.now() + timedelta(minutes=15))
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.config = {"warehouse_ids": [3], "platform_ids": [1]}
    scope.save()
    with patch("apps.reports.async_exports.create_export_request") as build:
        run_export(job.pk)
    job.refresh_from_db()
    assert job.status == "failed"
    assert "报表导出数据范围配置不兼容" in job.error
    assert not job.worker_active
    build.assert_not_called()
