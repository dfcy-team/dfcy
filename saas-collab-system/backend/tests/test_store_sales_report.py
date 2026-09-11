from decimal import Decimal
import pytest
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for

pytestmark = pytest.mark.django_db


def test_multi_platform_store_filters_intersect_and_preserve_tenant_scope():
    from apps.masterdata.models import PlatformMaster, StoreMaster
    from apps.reports.export_services import _apply_sales_detail_filters
    from apps.commerce.models import SalesOrder
    tenant, _, first, _ = create_scope("multi")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TikTok", platform_type="shopee")
    second = StoreMaster.objects.create(tenant=tenant, platform=platform, code="TK", name="TK", currency="PHP", country_code="PH", timezone="Asia/Manila")
    create_order(tenant, first, "multi-first")
    create_order(tenant, second, "multi-second")
    platform.platform_type = "tiktok"
    platform.save(update_fields=["platform_type"])
    other, _, hidden, _ = create_scope("multi-hidden")
    create_order(other, hidden, "multi-hidden")
    viewer = user_for(tenant, "multi-viewer")
    grant(viewer, "sales_management.stores.view")
    client = client_for(viewer)
    path = "/api/internal/commerce/sales/stores/"
    params = {"platforms": "shopee,tiktok", "store_ids": f"{first.id},{second.id},{hidden.id}", "date_from": "2026-08-01", "date_to": "2026-08-31"}
    response = client.get(path, params)
    assert response.status_code == 200
    assert {row["store_id"] for row in response.json()["data"]["results"]} == {first.id, second.id}
    params["platforms"] = "tiktok"
    assert client.get(path, params).json()["data"]["count"] == 1
    for invalid in ["abc", "1,-2", "999999999999999999999999999999999"]:
        assert client.get(path, {"store_ids": invalid}).status_code == 400
    exported = _apply_sales_detail_filters(SalesOrder.objects.filter(tenant=tenant), {"platforms": ["shopee", "tiktok"], "store_ids": [first.id, second.id]})
    assert set(exported.values_list("store_id", flat=True)) == {first.id, second.id}


def test_store_report_uses_full_scope_for_summary_and_trend_before_pagination():
    tenant, platform, store, _ = create_scope("report")
    from apps.masterdata.models import StoreMaster
    second = StoreMaster.objects.create(tenant=tenant, platform=platform, code="SECOND", name="Second",
                                       currency="PHP", country_code="PH", timezone="Asia/Manila")
    create_order(tenant, store, "report", "100")
    cancelled = create_order(tenant, store, "cancel", "50")
    cancelled.normalized_status = "cancelled"
    cancelled.save()
    create_order(tenant, second, "second", "900")
    other, _, hidden, _ = create_scope("hidden-report")
    create_order(other, hidden, "hidden-report", "999999")
    viewer = user_for(tenant, "report-viewer")
    grant(viewer, "sales_management.stores.view")
    client = client_for(viewer)
    path = "/api/internal/sales-management/stores/"
    response = client.get(path, {"page_size": 1, "ordering": "-gross_sales"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 2
    assert data["results"][0]["store_id"] == second.id
    metrics = {m["code"]: Decimal(m["value"]) for m in data["currency_groups"][0]["metrics"]}
    assert metrics["gross_sales"] == 1000
    assert metrics["order_count"] == 3
    assert metrics["valid_order_count"] == 2
    assert metrics["cancelled_amount"] == 50
    assert sum(row['order_count'] for row in data['metric_daily']) == 3
    assert sum(row['units_sold'] for row in data['metric_daily']) == 6
    assert sum(Decimal(str(row['cancelled_amount'])) for row in data['metric_daily']) == 50
    assert sum(Decimal(row["gross_sales"]["PHP"]) for row in data["trend"]) == 1000
    page2 = client.get(path, {"page_size": 1, "page": 2, "ordering": "-gross_sales"}).json()["data"]
    assert page2["results"][0]["cancelled_order_count"] == 1
    assert client.get(path, {"ordering": "token"}).status_code == 400
    scoped = client.get(path, {"store_id": second.id}).json()["data"]
    assert scoped["count"] == 1
    assert Decimal(scoped["currency_groups"][0]["metrics"][0]["value"]) == 1
