import pytest

from apps.permissions.models import DataScope, RoleResourcePolicy
from apps.masterdata.models import StoreMaster
from apps.reports.export_services import _self_service_access
from rest_framework.exceptions import PermissionDenied
from apps.reports.models import ReportExportRequest
from tests.test_report_resource_scope import _explicit, _report_role
from tests.test_report_revision import _config
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def setup_explicit(code):
    tenant, _, store, _ = create_scope(code)
    create_order(tenant, store, code)
    viewer = user_for(tenant, code)
    grant(viewer, "reports.view", DataScope.ScopeType.CUSTOM,
          {"platform_ids": [store.platform_id], "warehouse_ids": [1]})
    role = _report_role(viewer, code + "-report")
    policy = _explicit(viewer, role, "reports.sales", {"store_ids": [store.pk]})
    grant(viewer, "sales_management.view", DataScope.ScopeType.ALL)
    grant(viewer, "sales_management.export", DataScope.ScopeType.ALL)
    return viewer, store, policy


def test_catalog_and_own_history_use_existing_explicit_report_policy():
    user, _, _ = setup_explicit("export-catalog-explicit")
    client = client_for(user)
    response = client.get("/api/report/catalog/")
    assert response.status_code == 200
    assert {row["report_type"] for row in response.data["data"]} == {"sales_details", "self_service"}
    response = client.get("/api/report/exports/")
    assert response.status_code == 200
    assert response.data["data"]["count"] == 0
    # Metadata visibility never grants export execution.
    assert client.post("/api/report/exports/", {"report_type": "self_service",
        "filters": {"config": _config("sales", ["store_id"], ["order_count"])}}, format="json").status_code == 403


def test_invalid_legacy_scope_without_valid_explicit_policy_remains_denied():
    user, _, policy = setup_explicit("export-catalog-no-policy")
    policy.delete()
    assert client_for(user).get("/api/report/catalog/").status_code == 403
    assert client_for(user).get("/api/report/exports/").status_code == 403


def test_foreign_explicit_store_cannot_authorize_catalog():
    user, _, policy = setup_explicit("export-catalog-foreign")
    _, _, foreign, _ = create_scope("export-catalog-other-tenant")
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config={"store_ids": [foreign.pk]})
    assert client_for(user).get("/api/report/catalog/").status_code == 403


def test_explicit_report_scope_is_part_of_export_fingerprint_and_download_recheck(tmp_path, settings):
    settings.REPORT_EXPORT_ROOT = tmp_path
    user, store, policy = setup_explicit("export-resource-revoke")
    second = StoreMaster.objects.create(tenant=user.tenant, platform=store.platform,
        code="export-second-store", name="Second", country_code="PH", currency="PHP", timezone="Asia/Manila")
    policy.config = {"store_ids": [store.pk, second.pk]}
    policy.save()
    for code in ("reports.export", "reports.download"):
        grant(user, code, DataScope.ScopeType.ALL)
    config = _config("sales", ["store_id"], ["order_count"])
    _, _, before = _self_service_access(user, config)
    from apps.reports.async_exports import export_fingerprint
    _, fingerprint_before = export_fingerprint(user, "self_service", {"config": config})
    client = client_for(user)
    response = client.post("/api/report/exports/", {"report_type": "self_service", "filters": {"config": config}}, format="json")
    assert response.status_code == 201, response.content
    export_id = response.data["data"]["id"]
    assert ReportExportRequest.objects.get(pk=export_id).row_count == 1
    # Old finance configuration and unversioned snapshots must not reappear
    # merely because one sales dataset is currently visible.
    for hidden_config, hidden_snapshot in [
        (_config("finance", ["currency"], ["transaction_count"]), before),
        (config, {}),
    ]:
        historical = ReportExportRequest(tenant=user.tenant, requested_by=user,
            report_type="self_service", status="completed", source_scope=hidden_snapshot,
            filters={"config": hidden_config}, row_count=123)
        historical._export_service_write = True
        historical.save()
        assert client.get(f"/api/report/exports/{historical.pk}/").status_code == 404
    foreign_tenant, _, _, _ = create_scope("export-history-foreign")
    for owner in [user_for(user.tenant, "export-history-peer"),
                  user_for(foreign_tenant, "export-history-foreign-user")]:
        historical = ReportExportRequest(tenant=owner.tenant, requested_by=owner,
            report_type="self_service", status="completed", source_scope=before,
            filters={"config": config}, row_count=456)
        historical._export_service_write = True
        historical.save()
        assert client.get(f"/api/report/exports/{historical.pk}/").status_code == 404
    history = client.get("/api/report/exports/")
    assert history.status_code == 200
    assert [row["id"] for row in history.data["data"]["results"]] == [export_id]
    grant_response = client.post(f"/api/report/exports/{export_id}/download/", {}, format="json")
    assert grant_response.status_code == 200
    reference = grant_response.data["data"]["download_reference"]
    response = client.get(reference)
    assert response.status_code == 200
    assert b"".join(response.streaming_content)
    if response.file_to_stream is not None:
        response.file_to_stream.close()
    policy.config = {"store_ids": [store.pk]}
    policy.save()
    _, _, narrowed = _self_service_access(user, config)
    _, fingerprint_after = export_fingerprint(user, "self_service", {"config": config})
    assert narrowed != before
    assert fingerprint_after != fingerprint_before
    assert client.post(f"/api/report/exports/{export_id}/download/", {}, format="json").status_code == 403
    assert client.get(reference).status_code == 403
    assert client.get("/api/report/exports/").data["data"]["count"] == 0
    # A policy change must invalidate both fresh grants and previously issued URLs.
    policy.delete()
    assert client.post(f"/api/report/exports/{export_id}/download/", {}, format="json").status_code == 403
    assert client.get(reference).status_code == 403
    with pytest.raises(PermissionDenied) as failure:
        _self_service_access(user, config)
    assert getattr(failure.value, "status_code", None) == 403
    assert before["reports.view"]
