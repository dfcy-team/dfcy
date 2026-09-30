import pytest

from apps.permissions.models import DataScope
from apps.reports.datasets import normalize_config
from apps.reports.dashboard_config import normalize_dashboard
from rest_framework.exceptions import ValidationError
from tests.test_sales_management import client_for, create_scope, grant, user_for


pytestmark = pytest.mark.django_db
VIEWS = "/api/report/views/"


def _config(dataset="sales"):
    return {"dataset": dataset, "dimensions": ["store_id"], "metrics": ["order_count"], "filters": {}, "chart": "table"}


def _dashboard(module="经营分析", widgets=None):
    return {
        "kind": "dashboard", "version": 1, "module": module,
        "filters": {"date_from": "2026-01-01", "date_to": "2026-01-31"},
        "widgets": widgets or [{"id": "widget-1", "title": "Orders", "type": "card", "width": 6, "height": 240, "config": _config()}],
    }


def _report_access(user, *codes):
    grant(user, "reports.view")
    for code in codes:
        grant(user, code)


def test_field_layout_normalizes_currency_to_rows_and_rejects_invalid_layout():
    normalized = normalize_config({
        "dataset": "sales", "dimensions": ["store_id"], "metrics": ["gross_sales"], "filters": {},
        "field_layout": {"rows": [], "columns": ["store_id"], "filters": []},
    })
    assert normalized["dimensions"] == ["store_id", "currency"]
    assert normalized["field_layout"] == {"rows": ["currency"], "columns": ["store_id"], "filters": []}
    with pytest.raises(ValidationError):
        normalize_config({**_config(), "field_layout": {"rows": ["store_id"], "columns": ["store_id"], "filters": []}})
    with pytest.raises(ValidationError):
        normalize_config({**_config(), "field_layout": {"rows": ["store_id"], "columns": [], "filters": ["warehouse_id"]}})


def test_dashboard_save_restore_and_strict_contract_validation():
    tenant, _, _, _ = create_scope("bi-dashboard-contract")
    owner = user_for(tenant, "bi-dashboard-owner")
    _report_access(owner, "sales_management.view")
    client = client_for(owner)
    created = client.post(VIEWS, {"name": "Operations", "is_shared": True, "config": _dashboard()}, format="json")
    assert created.status_code == 201
    stored = created.json()["data"]["config"]
    assert stored["kind"] == "dashboard" and stored["widgets"][0]["config"]["dataset"] == "sales"
    assert client.get(VIEWS).json()["data"][0]["id"] == created.json()["data"]["id"]
    bad_cases = [
        {**_dashboard(), "widgets": []},
        {**_dashboard(), "module": "库存管理"},
        {**_dashboard(), "widgets": [{**_dashboard()["widgets"][0], "width": 7}]},
        {**_dashboard(), "widgets": [{**_dashboard()["widgets"][0]}, {**_dashboard()["widgets"][0]}]},
    ]
    for bad in bad_cases:
        assert client.post(VIEWS, {"name": "Invalid", "config": bad}, format="json").status_code == 400


def test_shared_dashboard_is_hidden_when_viewer_lacks_any_widget_permission_or_report_type():
    tenant, _, _, _ = create_scope("bi-dashboard-shared")
    owner = user_for(tenant, "bi-dashboard-shared-owner")
    viewer = user_for(tenant, "bi-dashboard-shared-viewer")
    _report_access(owner, "sales_management.view", "finance.view")
    _report_access(viewer, "sales_management.view")
    dashboard = _dashboard(widgets=[
        _dashboard()["widgets"][0],
        {"id": "widget-2", "title": "Finance", "type": "table", "width": 12, "height": 320,
         "config": {"dataset": "finance", "dimensions": ["currency"], "metrics": ["transaction_count"], "filters": {}, "chart": "table"}},
    ])
    created = client_for(owner).post(VIEWS, {"name": "Cross module", "is_shared": True, "config": dashboard}, format="json")
    assert created.status_code == 201
    assert client_for(viewer).get(VIEWS).json()["data"] == []
    grant(viewer, "finance.view")
    assert len(client_for(viewer).get(VIEWS).json()["data"]) == 1
    scope = DataScope.objects.get(role__user_roles__user=viewer, role__permissions__code="reports.view")
    scope.config = {"report_types": ["finance_summary"]}
    scope.scope_type = DataScope.ScopeType.CUSTOM
    scope.save(update_fields=["config", "scope_type"])
    assert client_for(viewer).get(VIEWS).json()["data"] == []


@pytest.mark.parametrize("change", [
    {"version": True}, {"version": 2}, {"module": []}, {"filters": {"sql": "select 1"}},
    {"filters": {"date_from": "2026-02-02", "date_to": "2026-01-01"}},
    {"filters": {"warehouse_id": "-1"}},
])
def test_dashboard_rejects_invalid_global_contract_without_server_errors(change):
    with pytest.raises(ValidationError):
        normalize_dashboard({**_dashboard(), **change})


@pytest.mark.parametrize("change", [
    {"type": []}, {"width": []}, {"height": True}, {"height": 239}, {"height": 721},
    {"title": " "}, {"id": ""}, {"config": {"dataset": "unknown"}},
])
def test_dashboard_rejects_invalid_widget_contract_without_server_errors(change):
    widget = {**_dashboard()["widgets"][0], **change}
    with pytest.raises(ValidationError):
        normalize_dashboard(_dashboard(widgets=[widget]))


def test_dashboard_is_tenant_scoped_owner_mutable_and_never_accepted_as_a_query():
    tenant, _, _, _ = create_scope("bi-dashboard-isolation")
    other_tenant, _, _, _ = create_scope("bi-dashboard-other")
    owner = user_for(tenant, "bi-isolation-owner")
    colleague = user_for(tenant, "bi-isolation-colleague")
    outsider = user_for(other_tenant, "bi-isolation-outsider")
    for user in [owner, colleague, outsider]:
        _report_access(user, "sales_management.view")
    client = client_for(owner)
    body = {"name": "Tenant board", "is_shared": True, "config": _dashboard()}
    created = client.post(VIEWS, body, format="json")
    assert created.status_code == 201
    view_id = created.json()["data"]["id"]
    assert len(client_for(colleague).get(VIEWS).json()["data"]) == 1
    assert client_for(outsider).get(VIEWS).json()["data"] == []
    assert client_for(colleague).put(f"{VIEWS}{view_id}/", body, format="json").status_code == 404
    assert client_for(outsider).delete(f"{VIEWS}{view_id}/").status_code == 404
    assert client.post("/api/report/query/", _dashboard(), format="json").status_code == 400
    assert client.put(f"{VIEWS}{view_id}/", {**body, "name": "Updated"}, format="json").status_code == 200
    assert client.delete(f"{VIEWS}{view_id}/").status_code == 200


def test_chart_and_field_layout_changes_reuse_scoped_data_cache_and_keep_current_presentation():
    tenant, _, _, _ = create_scope("bi-presentation-cache")
    viewer = user_for(tenant, "bi-cache-viewer")
    _report_access(viewer, "sales_management.view")
    client = client_for(viewer)
    config = _config()
    first = client.post("/api/report/query/", config, format="json")
    assert first.status_code == 200 and not first.json()["data"]["cached"]
    changed = {**config, "chart": "bar", "chart_metric": "order_count", "field_layout": {"rows": ["store_id"], "columns": [], "filters": []}}
    second = client.post("/api/report/query/", changed, format="json")
    assert second.status_code == 200
    result = second.json()["data"]
    assert result["cached"] and result["config"]["chart"] == "bar"
    assert result["config"]["field_layout"]["filters"] == []
