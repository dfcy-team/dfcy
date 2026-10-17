from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from rest_framework.exceptions import ValidationError

from apps.reports.analysis_jobs import run_analysis
from apps.reports.models import ReportAnalysisJob
from apps.reports.period_analysis import aggregate_window, normalize_analysis, period_slots
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


def test_iso_year_53_and_month_progress():
    slots = period_slots({"mode": "weekly", "year": 2026, "cutoff": "2027-01-03"})
    assert len(slots) == 53
    assert slots[0]["start"] == "2025-12-29"
    assert slots[-1]["yoy"] is None
    monthly = period_slots({"mode": "monthly", "year": 2026, "cutoff": "2026-10-15"})
    assert len(monthly) == 12
    assert monthly[9]["current"]["date_to"] == "2026-10-15"
    assert monthly[9]["yoy"]["date_to"] == "2025-10-15"
    assert monthly[9]["previous"]["date_to"] == "2026-09-15"
    assert monthly[10]["future"] and monthly[10]["current"] is None


def test_missing_and_zero_are_different_and_ratios_weighted():
    window = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    assert aggregate_window([], window, ["expense"], "advertising") is None
    rows = [{"date": "2026-01-01", "expense": "10", "clicks": 5, "impressions": 10, "direct_gmv": "0", "broad_gmv": None},
            {"date": "2026-01-02", "expense": "20", "clicks": 5, "impressions": 90, "direct_gmv": "60", "broad_gmv": "90"}]
    result = aggregate_window(rows, window, ["expense", "clicks", "impressions", "direct_gmv", "broad_gmv"], "advertising")
    assert result["metrics"]["ctr"] == "10.0"
    assert result["metrics"]["direct_roas"] == "2"
    assert result["metrics"]["broad_roas"] is None
    assert result["coverage"] == "unverified"


def test_rejects_oversized_period_and_unvalidated_filters():
    with pytest.raises(ValidationError):
        normalize_analysis({"mode": "period", "date_from": "2025-01-01", "date_to": "2026-12-31"})
    with pytest.raises(ValidationError):
        normalize_analysis({"filters": {"date_from": "2020-01-01"}})


@pytest.mark.django_db
@patch("apps.reports.period_analysis.timezone.now", return_value=datetime(2026, 10, 16, 18, tzinfo=UTC))
def test_async_sales_result_dedup_currency_drill_and_revocation(_mock_now):
    cache.clear()
    tenant, _, store, _ = create_scope("period-job")
    order = create_order(tenant, store, "period-job", "125")
    viewer = user_for(tenant, "period-viewer")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    client = client_for(viewer)
    response = client.post("/api/report/analysis-jobs/", {"dataset": "sales", "year": 2026}, format="json")
    assert response.status_code == 202, response.data
    job_id = response.data["data"]["id"]
    same = client.post("/api/report/analysis-jobs/", {"dataset": "sales", "year": 2026}, format="json")
    assert same.data["data"]["id"] == job_id
    run_analysis(job_id)
    result = client.get(f"/api/report/analysis-jobs/{job_id}/").data["data"]
    assert result["status"] == "completed", result
    series = result["result"]["series"]
    assert len(series) == 1 and series[0]["currency"] == "PHP"
    august = series[0]["points"][7]
    assert august["current"]["metrics"]["gross_sales"] == "125"
    assert august["drill"]["current"]["date_from"] == "2026-08-01"
    assert august["yoy"] is None
    assert series[0]["points"][0]["current"] is None
    other = user_for(tenant, "period-other")
    grant(other, "reports.view")
    grant(other, "sales_management.view")
    assert client_for(other).get(f"/api/report/analysis-jobs/{job_id}/").status_code == 404
    viewer.user_roles.filter(role__permissions__code="sales_management.view").delete()
    assert client.get(f"/api/report/analysis-jobs/{job_id}/").status_code == 403


@pytest.mark.django_db
def test_cancel_prevents_worker_and_expired_snapshot_hidden():
    tenant, _, _, _ = create_scope("cancel-period")
    viewer = user_for(tenant, "cancel-viewer")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    client = client_for(viewer)
    created = client.post("/api/report/analysis-jobs/", {"year": 2026}, format="json")
    job_id = created.data["data"]["id"]
    assert client.delete(f"/api/report/analysis-jobs/{job_id}/").data["data"]["status"] == "cancelled"
    run_analysis(job_id)
    assert ReportAnalysisJob.objects.get(pk=job_id).result is None


@pytest.mark.django_db
def test_inventory_comparison_preserves_missing_source_quantity():
    from apps.commerce.models import InventorySnapshot
    from tests.test_sales_management import create_run
    from apps.reports.period_analysis import build_analysis
    from types import SimpleNamespace
    tenant, _, _, warehouse = create_scope("inventory-period")
    run = create_run(tenant, "inventory_snapshot", "inventory-period", platform="jifeng_wms")
    viewer = user_for(tenant, "inventory-period-user")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    for day, qty, provided in [(1, 10, ["available_qty"]), (2, 0, [])]:
        InventorySnapshot.objects.create(tenant=tenant, warehouse=warehouse, source_run=run, site_code="PH", source_sku="S1", snapshot_at_utc=datetime(2026, 1, day, tzinfo=UTC), available_qty=qty, on_hand_qty=qty, provided_quantity_fields=provided, payload_hash=str(day)*64)
    config = {"dataset":"inventory", "mode":"period", "date_from":"2026-01-01", "date_to":"2026-01-02", "cutoff":"2026-01-03", "filters":{}}
    result = build_analysis(SimpleNamespace(user=viewer), config)
    row = result["rows"][0]
    assert row["previous"]["provided_available"] == "10"
    assert row["current"]["provided_available"] is None
    assert row["delta"]["provided_available"] is None
    assert row["current"]["snapshot_newest"].date() == date(2026,1,2)


@pytest.mark.django_db
def test_grouped_comparison_keeps_all_weeks_and_country_drill():
    from apps.reports.period_analysis import build_analysis
    from types import SimpleNamespace
    tenant, _, store, _ = create_scope("group-period")
    order = create_order(tenant, store, "group-period")
    from apps.commerce.models import SalesOrder
    SalesOrder.objects.filter(pk=order.pk).update(region="")
    viewer = user_for(tenant, "group-period-user")
    grant(viewer, "reports.view")
    grant(viewer, "sales_management.view")
    result = build_analysis(SimpleNamespace(user=viewer), {"dataset":"sales", "mode":"weekly", "year":2026, "cutoff":"2026-10-15", "filters":{}, "group_by":"country"})
    group = result["groups"][0]
    assert len(group["points"]) == 53
    point = next(point for point in group["points"] if point["current"])
    assert point["drill"]["current"]["region"] == "PH"
    assert group["currency"] == "PHP"
    grant(viewer, "sales_management.orders.view")
    response = client_for(viewer).get("/api/internal/sales-management/orders/", point["drill"]["current"])
    assert response.status_code == 200, response.data
    assert response.data["data"]["count"] == 1


@pytest.mark.django_db
def test_ads_integrated_dataset_has_real_refresh_and_guarded_numbers():
    from apps.integrations.models import ShopeeAdvertisingRecord
    from tests.test_sales_management import create_run
    tenant, _, store, _ = create_scope("period-ad-api")
    source = create_run(tenant,"advertising_report","period-ad-api")
    ShopeeAdvertisingRecord.objects.create(tenant=tenant,store=store,source_run=source,kind="shop_daily",record_key="day",report_date=date(2026,1,1),currency="PHP",report_timezone="Asia/Manila",data={"expense":"12.50","clicks":2,"impression":10,"direct_gmv":"25","broad_gmv":"30"})
    viewer = user_for(tenant,"period-ad-user")
    grant(viewer,"reports.view")
    grant(viewer,"analytics.view")
    response = client_for(viewer).post("/api/report/query/",{"dataset":"advertising","dimensions":["date","country","currency"],"metrics":["expense","clicks"],"filters":{"date_from":"2026-01-01","date_to":"2026-01-31","region":"PH"}},format="json")
    assert response.status_code==200,response.data
    assert response.data["data"]["rows"][0]["country"]=="PH"
    assert response.data["data"]["refreshed_at"] is not None
