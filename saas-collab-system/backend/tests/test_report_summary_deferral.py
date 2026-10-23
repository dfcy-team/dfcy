from unittest.mock import patch

import pytest

from apps.integrations.models import APIDataQualityCheck, APISyncLog, APISyncTask
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from apps.sales_management import views
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


pytestmark = pytest.mark.django_db


def test_compact_overview_can_skip_quality_aggregates_without_changing_sales_metrics():
    tenant, _, store, _ = create_scope("summary-deferral-overview")
    create_order(tenant, store, "summary-deferral", "125.0000")
    user = user_for(tenant, "summary-deferral-overview-viewer")
    grant(user, "sales_management.view")
    client = client_for(user)

    with patch("apps.sales_management.views._sales_quality", wraps=views._sales_quality) as quality_aggregate:
        default = client.get("/api/internal/sales-management/overview/", {"compact": "true"})
        quality_aggregate.assert_called_once()

    with patch("apps.sales_management.views._sales_quality") as quality_aggregate:
        deferred = client.get("/api/internal/sales-management/overview/", {
            "compact": "true", "include_quality": "false",
        })
        quality_aggregate.assert_not_called()

    assert default.status_code == deferred.status_code == 200
    default_data, deferred_data = default.json()["data"], deferred.json()["data"]
    assert deferred_data["metrics"] == default_data["metrics"]
    assert deferred_data["currency_groups"] == default_data["currency_groups"]
    assert deferred_data["quality"]["status"] == "not_evaluated"
    assert deferred_data["quality"]["score"] is None
    assert deferred_data["quality"]["checked_rows"] is None
    assert deferred_data["quality"]["problem_rows"] is None
    assert deferred_data["quality"]["refreshed_at"] == default_data["quality"]["refreshed_at"]


def test_quality_screen_can_defer_summary_and_keeps_authorized_issues_and_default_behavior():
    tenant, _, visible_store, _ = create_scope("summary-deferral-quality")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=visible_store.platform, code="summary-deferral-hidden", name="Hidden",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    checks = []
    for store, suffix in ((visible_store, "visible"), (hidden_store, "hidden")):
        task = APISyncTask.objects.create(
            tenant=tenant, platform="shopee", sync_type=APISyncTask.SyncType.SALES_ORDER,
            config={"store_id": str(store.id), "store_code": store.code},
        )
        log = APISyncLog.objects.create(tenant=tenant, task=task, status=APISyncTask.Status.FAILED)
        checks.append(APIDataQualityCheck.objects.create(
            tenant=tenant, sync_log=log, check_type=f"deferred-{suffix}", status=APIDataQualityCheck.Status.FAILED,
        ))
    create_order(tenant, visible_store, "summary-deferral-quality-order", "40.0000")
    user = user_for(tenant, "summary-deferral-quality-viewer")
    grant(user, "sales_management.data_quality.view", DataScope.ScopeType.CUSTOM,
          {"store_ids": [str(visible_store.id)]})
    client = client_for(user)

    with patch("apps.sales_management.views._sales_page_context") as summary_context:
        deferred = client.get("/api/internal/commerce/quality/", {"include_summary": "false"})
        summary_context.assert_not_called()

    assert deferred.status_code == 200
    deferred_data = deferred.json()["data"]
    assert [row["id"] for row in deferred_data["issues"]] == [checks[0].id]
    assert deferred_data["sources"] == []
    assert deferred_data["source_status"] == "unknown"
    assert deferred_data["summary_metrics"] == []
    assert deferred_data["summary_status"] == "not_requested"
    assert deferred_data["quality"]["status"] == "not_evaluated"
    assert deferred_data["quality"]["score"] is None

    with patch("apps.sales_management.views._sales_page_context", wraps=views._sales_page_context) as summary_context:
        default = client.get("/api/internal/commerce/quality/")
        summary_context.assert_called_once()
    assert default.status_code == 200
    default_data = default.json()["data"]
    assert default_data["summary_metrics"]
    assert default_data["quality"]["checked_rows"] is not None
