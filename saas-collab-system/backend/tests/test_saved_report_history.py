import pytest

from apps.permissions.models import DataScope
from apps.reports.models import SavedReportViewRevision
from tests.test_sales_management import client_for, create_scope, grant, user_for

pytestmark = pytest.mark.django_db
VIEWS = "/api/report/views/"
CONFIG = {"dataset": "sales", "dimensions": ["store_id"], "metrics": ["order_count"], "filters": {}}


def _owner(tenant, suffix):
    user = user_for(tenant, suffix)
    grant(user, "reports.view")
    grant(user, "sales_management.view")
    return user


def test_view_revisions_increment_and_archive_without_losing_history():
    tenant, _, _, _ = create_scope("view-history")
    owner = _owner(tenant, "view-history-owner")
    client = client_for(owner)
    created = client.post(VIEWS, {"name": "First", "config": CONFIG, "is_shared": True}, format="json")
    pk = created.json()["data"]["id"]
    assert created.json()["data"]["version"] == 1
    updated = client.put(f"{VIEWS}{pk}/", {"name": "Second", "config": CONFIG, "expected_version": 1}, format="json")
    assert updated.json()["data"]["version"] == 2
    assert client.put(f"{VIEWS}{pk}/", {"name": "Stale", "config": CONFIG, "expected_version": 1}, format="json").status_code == 400
    history_url = f"{VIEWS}{pk}/history/"
    revisions = client.get(history_url).json()["data"]
    assert [(row["version"], row["name"], row["action"]) for row in revisions] == [(1, "First", "create"), (2, "Second", "update")]
    assert client.delete(f"{VIEWS}{pk}/").json()["data"] == {"deleted": True}
    assert client.get(VIEWS).json()["data"] == []
    archived = client.get(history_url).json()["data"]
    assert [row["action"] for row in archived] == ["create", "update", "archive"]
    assert archived[-1]["version"] == 3
    assert SavedReportViewRevision.objects.filter(view_id=pk).count() == 3


def test_view_history_is_owner_only_and_rechecks_current_business_permission():
    tenant, _, _, _ = create_scope("view-history-permission")
    owner = _owner(tenant, "view-history-permission-owner")
    other = _owner(tenant, "view-history-permission-other")
    client = client_for(owner)
    created = client.post(VIEWS, {"name": "Private", "config": CONFIG}, format="json")
    pk = created.json()["data"]["id"]
    assert client_for(other).get(f"{VIEWS}{pk}/history/").status_code == 404
    scope = DataScope.objects.get(role__user_roles__user=owner, role__permissions__code="sales_management.view")
    scope.delete()
    assert client.get(f"{VIEWS}{pk}/history/").status_code == 403


def test_legacy_baseline_backfill_is_batched_and_does_not_invent_old_revisions():
    import importlib
    from django.apps import apps
    from apps.reports.models import SavedReportView
    tenant, _, _, _ = create_scope("history-baseline")
    owner = _owner(tenant, "history-baseline-owner")
    SavedReportView.objects.bulk_create([
        SavedReportView(tenant=tenant, owner=owner, name=f"legacy-{i}", config=CONFIG) for i in range(501)
    ], batch_size=500)
    migration = importlib.import_module("apps.reports.migrations.0009_saved_report_view_history")
    migration.backfill_revisions(apps, None)
    assert SavedReportViewRevision.objects.filter(action="baseline", version=1).count() == 501
    assert SavedReportViewRevision.objects.exclude(config=CONFIG).count() == 0
    assert SavedReportViewRevision.objects.filter(action="create").count() == 0


def test_history_authorization_query_budget_does_not_grow_with_versions():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from apps.reports.models import SavedReportView
    tenant, _, _, _ = create_scope("history-query-budget")
    owner = _owner(tenant, "history-query-budget-owner")
    client = client_for(owner)
    view_id = client.post(VIEWS, {"name": "History", "config": CONFIG}, format="json").json()["data"]["id"]
    with CaptureQueriesContext(connection) as small:
        assert client.get(f"{VIEWS}{view_id}/history/").status_code == 200
    SavedReportViewRevision.objects.bulk_create([
        SavedReportViewRevision(view_id=view_id, version=version, config=CONFIG, name="History", action="update", actor=owner) for version in range(2, 22)
    ])
    with CaptureQueriesContext(connection) as large:
        assert len(client.get(f"{VIEWS}{view_id}/history/").json()["data"]) == 21
    assert len(large) <= len(small) + 1
