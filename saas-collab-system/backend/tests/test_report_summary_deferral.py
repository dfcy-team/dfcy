from unittest.mock import patch

import pytest

from apps.commerce.models import RefundReturn
from apps.integrations.models import APIDataQualityCheck, APISyncLog, APISyncTask
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from apps.sales_management import views
from tests.test_sales_management import client_for, create_order, create_run, create_scope, grant, user_for


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


def test_quality_projection_matches_full_summary_and_skips_currency_summary():
    tenant, _, store, _ = create_scope("summary-quality-projection")
    create_order(tenant, store, "summary-quality-projection-order", "40.0000")
    user = user_for(tenant, "summary-quality-projection-viewer")
    grant(user, "sales_management.data_quality.view")
    client = client_for(user)

    full = client.get("/api/internal/commerce/quality/")
    with patch("apps.sales_management.views._currency_summary") as currency_summary:
        projected = client.get("/api/internal/commerce/quality/", {"summary_projection": "quality"})
        currency_summary.assert_not_called()

    assert full.status_code == projected.status_code == 200
    full_data, projected_data = full.json()["data"], projected.json()["data"]
    assert projected_data["quality"] == full_data["quality"]
    assert projected_data["refreshed_at"] == full_data["refreshed_at"]
    assert projected_data["source_status"] == full_data["source_status"]
    assert projected_data["definition"] == full_data["definition"]
    assert projected_data["summary_metrics"] == []

    grant(user, "sales_management.orders.view")
    orders = client.get("/api/internal/commerce/orders/", {"summary_projection": "quality"})
    assert orders.status_code == 200
    assert orders.json()["data"]["summary_metrics"]


def test_quality_projection_preserves_currency_status_refund_timestamp_and_custom_scope():
    from datetime import UTC, datetime

    tenant, platform, store, _ = create_scope("summary-quality-projection-edges")
    hidden_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="quality-hidden", name="Hidden",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    visible_order = create_order(tenant, store, "quality-projection-cancelled")
    visible_order.normalized_status = "cancelled"
    visible_order.currency = ""
    visible_order.updated_at_utc = datetime(2026, 8, 1, tzinfo=UTC)
    # Imported legacy anomalies may predate current model validation.
    with patch.object(type(visible_order), "full_clean"):
        visible_order.save(update_fields=["normalized_status", "currency", "updated_at_utc"])
    line = visible_order.items.get()
    line.currency = "SGD"
    with patch.object(type(line), "full_clean"):
        line.save(update_fields=["currency"])
    hidden_order = create_order(tenant, hidden_store, "quality-projection-hidden")
    hidden_order.updated_at_utc = datetime(2026, 10, 1, tzinfo=UTC)
    hidden_order.save(update_fields=["updated_at_utc"])

    completed_at = datetime(2026, 9, 1, tzinfo=UTC)
    for status, suffix, updated_at in (
        ("completed", "completed", completed_at),
        ("pending", "pending", datetime(2026, 11, 1, tzinfo=UTC)),
    ):
        RefundReturn.objects.create(
            tenant=tenant, platform=platform, store=store, sales_order=None,
            source_run=create_run(tenant, "refund_return", f"quality-projection-{suffix}"),
            external_return_id=f"QUALITY-{suffix}", case_type="return_refund",
            raw_status=status.upper(), normalized_status=status,
            requested_at_utc=updated_at, updated_at_utc=updated_at, currency="PHP",
            refund_amount="5.0000", is_partial_quantity_return=False,
            is_refund_amount_adjusted=False, payload_hash=(("a" if status == "completed" else "b") * 64),
        )

    user = user_for(tenant, "summary-quality-projection-edge-viewer")
    grant(user, "sales_management.data_quality.view", DataScope.ScopeType.CUSTOM,
          {"store_ids": [str(store.id)]})
    client = client_for(user)
    full = client.get("/api/internal/commerce/quality/")
    projected = client.get("/api/internal/commerce/quality/", {"summary_projection": "quality"})
    assert full.status_code == projected.status_code == 200
    full_data, projected_data = full.json()["data"], projected.json()["data"]
    assert projected_data["quality"] == full_data["quality"]
    assert projected_data["quality"]["refreshed_at"] == completed_at.isoformat().replace("+00:00", "Z")
    assert projected_data["refreshed_at"] == full_data["refreshed_at"]
    assert projected_data["source_status"] == full_data["source_status"] == "ready"

    empty_user = user_for(tenant, "summary-quality-projection-empty-viewer")
    grant(empty_user, "sales_management.data_quality.view", DataScope.ScopeType.CUSTOM, {"store_ids": []})
    empty = client_for(empty_user).get(
        "/api/internal/commerce/quality/", {"summary_projection": "quality"},
    )
    assert empty.status_code == 200
    assert empty.json()["data"]["source_status"] == "pending"
