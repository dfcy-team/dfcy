from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.commerce.models import SalesOrder
from apps.integrations.models import ShopeeAdvertisingRecord, SyncJob, SyncRun
from apps.permissions.models import DataScope
from tests.test_sales_realtime_board import _fixture, _grant, _order
from tests.test_observed_roi import _ad
from apps.masterdata.models import StoreMaster
from django.http import QueryDict
from django.db import DatabaseError
from types import SimpleNamespace
from rest_framework.exceptions import PermissionDenied
from apps.sales_management.sales_operations import _payload


URL = "/api/internal/commerce/sales-operations/"
NOW = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)


@pytest.mark.django_db
def test_current_uses_each_store_local_day_and_excludes_future_and_cancelled(monkeypatch):
    monkeypatch.setattr("apps.sales_management.current_sales_operations.timezone.now", lambda: NOW)
    user, tenant, platform, store, run, client = _fixture("current-local-window")
    store.timezone = "America/Los_Angeles"
    store.save(update_fields=["timezone"])
    for name, stamp, amount, status in [
        ("before-local-day", "2026-10-25T06:59:59+00:00", "500", "completed"),
        ("local-day", "2026-10-25T07:00:00+00:00", "10", "completed"),
        ("current", "2026-10-26T01:59:59+00:00", "20", "completed"),
        ("future", "2026-10-26T02:00:01+00:00", "900", "completed"),
        ("cancelled", "2026-10-25T08:00:00+00:00", "700", "cancelled"),
    ]:
        _order(tenant, platform, store, run, name, amount=amount, status=status)
        SalesOrder.objects.filter(tenant=tenant, external_order_id=name).update(created_at_utc=datetime.fromisoformat(stamp))
    response = client.get(URL, {"period": "current"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["period"] == "current"
    assert data["comparison_available"] is False
    assert data["generated_at"] == NOW.isoformat()
    assert data["filters"]["date_from"] == "2026-10-26"  # Beijing label; row uses Los Angeles day.
    row = data["rows"][0]
    assert row["sales_amount"] == "30"
    assert row["order_count"] == 2
    assert row["previous_sales_amount"] is None
    assert row["change_percent"] is None
    assert row["roi_delta"] is None
    assert row['business_date'] == '2026-10-25'
    assert row['units_sold'] == 4  # Platform lines without internal mapping still count.


@pytest.mark.django_db
def test_current_delivery_scope_partial_ads_and_failure_preserve_sales(monkeypatch):
    monkeypatch.setattr('apps.sales_management.current_sales_operations.timezone.now', lambda: NOW)
    user, tenant, platform, store, run, client = _fixture('current-delivery')
    _grant(user, 'analytics.view')
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code='other', name='Other', timezone='Asia/Manila', country_code='PH', currency='PHP')
    _order(tenant, platform, store, run, 'included', amount='100')
    _order(tenant, platform, other, run, 'no-ad', amount='900')
    SalesOrder.objects.filter(tenant=tenant).update(created_at_utc=datetime(2026, 10, 26, 1, tzinfo=UTC))
    _ad(tenant, store, run, 'good', '2026-10-26', 'PHP', '20')
    _ad(tenant, store, run, 'partial', '2026-10-26', 'PHP', 'bad')
    params = QueryDict('period=current&page_size=1')
    request = SimpleNamespace(user=user, query_params=params, delivery_store_ids=[store.pk, other.pk])
    data = _payload(request)
    assert data['has_next'] is True
    assert data['currency_groups'][0]['sales_amount'] == '1000'
    assert data['currency_groups'][0]['roi'] == '5'  # Only the matched store's GMV is numerator.
    _ad(tenant, other, run, 'zero-ad', '2026-10-26', 'PHP', '0')
    zero_mixed = _payload(request)
    assert zero_mixed['currency_groups'][0]['sales_amount'] == '1000'
    assert zero_mixed['currency_groups'][0]['ad_spend'] == '20'
    assert zero_mixed['currency_groups'][0]['roi'] == '5'
    request.delivery_store_ids = [other.pk]
    zero_only = _payload(request)
    assert zero_only['currency_groups'][0]['sales_amount'] == '900'
    assert zero_only['currency_groups'][0]['ad_spend'] == '0'
    assert zero_only['currency_groups'][0]['roi'] is None
    assert '为 0' in zero_only['currency_groups'][0]['ad_reason']
    request.delivery_store_ids = [store.pk]
    data = _payload(request)
    assert [row['store_id'] for row in data['rows']] == [store.pk]
    assert data['currency_groups'][0]['sales_amount'] == '100'
    request.delivery_store_ids = []
    assert _payload(request)['rows'] == []
    request.delivery_store_ids = [store.pk]
    def failed(*args, **kwargs):
        raise DatabaseError('unavailable')
    monkeypatch.setattr('apps.sales_management.current_sales_operations.advertising_queryset', failed)
    row = _payload(request)['rows'][0]
    assert row['sales_amount'] == '100'
    assert row['roi'] is None
    assert '暂不可用' in row['ad_reason']
    def denied(*args, **kwargs):
        raise PermissionDenied('incompatible analytics scope')
    monkeypatch.setattr('apps.sales_management.current_sales_operations.advertising_queryset', denied)
    row = _payload(request)['rows'][0]
    assert row['sales_amount'] == '100'
    assert row['roi'] is None
    assert '权限' in row['ad_reason']


@pytest.mark.django_db
def test_current_currency_roi_requires_analytics_permission_and_matches_store_currency(monkeypatch):
    monkeypatch.setattr("apps.sales_management.current_sales_operations.timezone.now", lambda: NOW)
    user, tenant, platform, store, run, client = _fixture("current-currency-roi")
    _order(tenant, platform, store, run, "php-current", currency="PHP", amount="200")
    _order(tenant, platform, store, run, "usd-current", currency="USD", amount="999")
    SalesOrder.objects.filter(tenant=tenant).update(created_at_utc=datetime(2026, 10, 26, 1, 0, tzinfo=UTC))
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=run.sync_job.integration_config, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(tenant=tenant, sync_job=ad_job, run_id="current-ad-run", idempotency_key="current-ad-key")
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key="current:php",
        report_date="2026-10-26", currency="PHP", report_timezone="Asia/Manila",
        source_run=ad_run, dimensions={"platform": "shopee"}, data={"expense": "20"},
    )

    no_permission = client.get(URL, {"period": "current"}).json()["data"]
    groups = {row["currency"]: row for row in no_permission["currency_groups"]}
    assert groups["PHP"]["ad_spend"] is None
    assert groups["PHP"]["roi"] is None
    assert groups["PHP"]["roi_delta"] is None
    assert groups["USD"]["ad_spend"] is None

    _grant(user, "analytics.view")
    with_permission = client.get(URL, {"period": "current"}).json()["data"]
    groups = {row["currency"]: row for row in with_permission["currency_groups"]}
    assert groups["PHP"]["ad_spend"] == "20"
    assert Decimal(groups["PHP"]["roi"]) == Decimal("10")
    assert groups["PHP"]["roi_delta"] is None
    assert groups["USD"]["ad_spend"] is None
    assert groups["USD"]["roi"] is None


@pytest.mark.django_db
def test_current_rejects_historical_and_product_parameters_and_honors_sales_scope(monkeypatch):
    monkeypatch.setattr("apps.sales_management.current_sales_operations.timezone.now", lambda: NOW)
    user, tenant, platform, store, run, client = _fixture("current-reject-scope")
    other = _order(tenant, platform, store, run, "current-visible", amount="20")
    SalesOrder.objects.filter(pk=other.pk).update(created_at_utc=datetime(2026, 10, 26, 1, 0, tzinfo=UTC))
    assert client.get(URL, {"period": "current", "date_from": "2026-10-25"}).status_code == 400
    assert client.get(URL, {"period": "current", "product_id": "x"}).status_code == 400

    # Replace the fixture's unrestricted sales scope with a custom empty scope.
    DataScope.objects.filter(tenant=tenant, role__permissions__code="sales_management.view").delete()
    _grant(user, "sales_management.view", {"store_ids": []})
    data = client.get(URL, {"period": "current"}).json()["data"]
    assert data["rows"] == []
    assert data["currency_groups"] == []
