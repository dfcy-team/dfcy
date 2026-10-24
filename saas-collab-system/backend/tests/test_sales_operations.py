from datetime import UTC, datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.masterdata.models import StoreMaster
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order


URL = "/api/internal/commerce/sales-operations/"


@pytest.mark.django_db
def test_utc_range_aggregation_keeps_dst_midnight_boundaries_without_date_functions():
    user, tenant, platform, store, run, client = _fixture('ops-dst-bounds')
    store.timezone = 'America/New_York'
    store.save(update_fields=['timezone'])
    for name, stamp, amount in [
        ('previous', '2026-03-08T04:59:59+00:00', '100'),
        ('start', '2026-03-08T05:00:00+00:00', '20'),
        ('end', '2026-03-09T03:59:59+00:00', '30'),
        ('outside', '2026-03-09T04:00:00+00:00', '500'),
    ]:
        _order(tenant, platform, store, run, name, amount=amount)
        SalesOrder.objects.filter(external_order_id=name, tenant=tenant).update(created_at_utc=datetime.fromisoformat(stamp))
    with CaptureQueriesContext(connection) as queries:
        response = client.get(URL, {'date_from': '2026-03-08', 'date_to': '2026-03-08'})
    assert response.status_code == 200
    row = response.json()['data']['rows'][0]
    assert row['sales_amount'] == '50'
    assert row['previous_sales_amount'] == '100'
    assert row['change_percent'] == '-50'
    fact_queries = [q['sql'].upper() for q in queries if 'SALES_ORDER' in q['sql'].upper()]
    assert all('DATE(' not in sql and 'DJANGO_DATETIME_CAST_DATE' not in sql for sql in fact_queries)


@pytest.mark.django_db
def test_previous_only_objects_remain_visible_without_fabricated_zero_drop():
    user, tenant, platform, store, run, client = _fixture('ops-previous-only')
    _grant(user, 'sales_management.skus.view')
    _order(tenant, platform, store, run, 'previous-only', amount='100')
    for view in ['stores', 'products']:
        data = client.get(URL, {'view': view, 'store_id': store.id, 'date_from': '2026-08-18', 'date_to': '2026-08-18'}).json()['data']
        assert len(data['rows']) == 1
        assert data['rows'][0]['sales_amount'] is None
        assert data['rows'][0]['previous_sales_amount'] == '100'
        assert data['rows'][0]['change_percent'] is None
        assert data['rows'][0]['observation_status'] == 'missing_current'
        assert data['currency_groups'][0]['sales_amount'] is None
        assert data['currency_groups'][0]['change_percent'] is None


@pytest.mark.django_db
def test_sales_operations_store_summary_and_bounded_pagination():
    user, tenant, platform, store, run, client = _fixture("ops-summary")
    for index in range(3):
        _order(tenant, platform, store, run, f"sale-{index}", amount="10")
    extra = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="extra", name="Extra", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    _order(tenant, platform, extra, run, "extra-sale", amount="5")
    response = client.get(URL, {"date_from": DAY, "date_to": DAY, "page_size": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["currency_groups"][0]["sales_amount"] == "35"
    assert data["rows"][0]["sales_amount"] == "30"
    assert data["rows"][0]["units_sold"] == 6
    assert data["has_next"] is True
    assert data["truncated"] is False
    second_page = client.get(URL, {"date_from": DAY, "date_to": DAY, "page": 2, "page_size": 1}).json()["data"]
    assert second_page["rows"][0]["sales_amount"] == "5"
    assert data["currency_groups"][0]["roi"] is None


@pytest.mark.django_db
def test_sorting_is_applied_before_pagination_and_exact_page_has_no_next():
    user, tenant, platform, store, run, client = _fixture("ops-sort-pages")
    for index in range(31):
        target = store if index == 0 else StoreMaster.objects.create(
            tenant=tenant, platform=platform, code=f"sort-{index}", name=f"Sort {index}",
            country_code="PH", currency=store.currency, timezone="Asia/Manila",
        )
        _order(tenant, platform, target, run, f"sorted-{index}", amount=str(index + 1))

    page = client.get(URL, {"date_from": DAY, "date_to": DAY, "sort": "sales_desc", "page_size": 30}).json()["data"]
    assert [row["sales_amount"] for row in page["rows"]] == [str(value) for value in range(31, 1, -1)]
    assert page["has_next"] is True
    last = client.get(URL, {"date_from": DAY, "date_to": DAY, "sort": "sales_desc", "page": 2, "page_size": 30}).json()["data"]
    assert [row["sales_amount"] for row in last["rows"]] == ["1"]
    assert last["has_next"] is False

    exact = client.get(URL, {"date_from": DAY, "date_to": DAY, "sort": "sales_desc", "page_size": 31}).json()["data"]
    assert len(exact["rows"]) == 31
    assert exact["has_next"] is False


@pytest.mark.django_db
def test_product_decline_filter_uses_strict_threshold_for_historical_day_and_keeps_summary_scope():
    user, tenant, platform, store, run, client = _fixture("ops-decline-filter")
    _grant(user, "sales_management.skus.view")
    historical_day = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=4)
    for name, amount, day, product_id in [
        ("strict-decline-prev", "100", historical_day - timedelta(days=1), "strict-decline"),
        ("strict-decline-current", "69", historical_day, "strict-decline"),
        ("exact-prev", "100", historical_day - timedelta(days=1), "exact-thirty"),
        ("exact-current", "70", historical_day, "exact-thirty"),
        ("missing-current-prev", "25", historical_day - timedelta(days=1), "missing-current"),
    ]:
        _order(tenant, platform, store, run, name, amount=amount)
        sale = SalesOrder.objects.get(external_order_id=name)
        sale.created_at_utc = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        sale.save(update_fields=["created_at_utc"])
        SalesOrderItem.objects.filter(sales_order=sale).update(platform_product_id=product_id)

    params = {"view": "products", "store_id": store.id, "date_from": historical_day.isoformat(), "date_to": historical_day.isoformat()}
    all_data = client.get(URL, params).json()["data"]
    changed = client.get(URL, {**params, "sort": "change_asc"}).json()["data"]
    filtered = client.get(URL, {**params, "status": "declines"}).json()["data"]
    assert [row["product_id"] for row in changed["rows"]] == ["strict-decline", "exact-thirty", "missing-current"]
    assert changed["rows"][0]["change_percent"] == "-31"
    assert changed["rows"][2]["sales_delta"] is None
    assert [row["product_id"] for row in filtered["rows"]] == ["strict-decline"]
    assert filtered["filters"]["status"] == "declines"
    assert filtered["currency_groups"] == all_data["currency_groups"]
    assert filtered["summary_scope"] == "all_filtered_stores"
    assert filtered["rows"][0]["sales_delta"] == "-31"
    assert filtered["rows"][0]["loss_amount"] == "31"

    missing = client.get(URL, {**params, "status": "unobserved"}).json()["data"]
    assert [row["product_id"] for row in missing["rows"]] == ["missing-current"]


@pytest.mark.django_db
def test_product_sort_modes_keep_decimal_ratios_and_nonpositive_baselines_last():
    user, tenant, platform, store, run, client = _fixture("ops-sort-modes")
    _grant(user, "sales_management.skus.view")
    historical_day = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=4)
    fixtures = [
        ("alpha-prev", "alpha", "3", historical_day - timedelta(days=1), 1),
        ("alpha-cur", "alpha", "2", historical_day, 1),
        ("beta-prev", "beta", "3", historical_day - timedelta(days=1), 1),
        ("beta-cur-a", "beta", "0.5", historical_day, 4),
        ("beta-cur-b", "beta", "0.5", historical_day, 4),
        ("zero-prev", "zero-baseline", "0", historical_day - timedelta(days=1), 1),
        ("zero-cur", "zero-baseline", "5", historical_day, 2),
        ("gain-prev", "gain", "2", historical_day - timedelta(days=1), 1),
        ("gain-cur", "gain", "4", historical_day, 3),
    ]
    for external_id, product_id, amount, day, quantity in fixtures:
        _order(tenant, platform, store, run, external_id, amount=amount)
        sale = SalesOrder.objects.get(external_order_id=external_id)
        sale.created_at_utc = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        sale.save(update_fields=["created_at_utc"])
        SalesOrderItem.objects.filter(sales_order=sale).update(
            platform_product_id=product_id, quantity=quantity, line_total_amount=amount,
        )

    base = {"view": "products", "store_id": store.id,
            "date_from": historical_day.isoformat(), "date_to": historical_day.isoformat()}
    def ids(sort):
        response = client.get(URL, {**base, "sort": sort})
        assert response.status_code == 200
        return [row["product_id"] for row in response.json()["data"]["rows"]]

    assert ids("change_asc") == ["beta", "alpha", "gain", "zero-baseline"]
    assert ids("loss_desc") == ["beta", "alpha", "gain", "zero-baseline"]
    assert ids("orders_desc") == ["beta", "alpha", "gain", "zero-baseline"]
    assert ids("units_desc") == ["beta", "gain", "zero-baseline", "alpha"]
    assert client.get(URL, {**base, "sort": "units_desc", "status": "bad"}).status_code == 400


@pytest.mark.django_db
def test_amount_sorting_separates_currencies_until_currency_is_selected():
    user, tenant, platform, store, run, client = _fixture("ops-currency-sort")
    _grant(user, "sales_management.skus.view")
    for index, (currency, amount) in enumerate([("USD", "100"), ("EUR", "1")]):
        external_id = f"currency-{index}"
        _order(tenant, platform, store, run, external_id, amount=amount)
        sale = SalesOrder.objects.get(external_order_id=external_id)
        sale.currency = currency
        sale.save(update_fields=["currency"])
        SalesOrderItem.objects.filter(sales_order=sale).update(platform_product_id=external_id, currency=currency)

    base = {"view": "products", "store_id": store.id, "date_from": DAY, "date_to": DAY, "sort": "sales_desc"}
    separated = client.get(URL, base).json()["data"]
    assert [row["currency"] for row in separated["rows"]] == ["EUR", "USD"]
    assert [group["currency"] for group in separated["currency_groups"]] == ["EUR", "USD"]
    assert any("按币种分别排序" in notice for notice in separated["notices"])

    narrowed = client.get(URL, {**base, "currency": "USD"}).json()["data"]
    assert [row["currency"] for row in narrowed["rows"]] == ["USD"]
    assert not any("按币种分别排序" in notice for notice in narrowed["notices"])


@pytest.mark.django_db
def test_products_require_sku_grant_and_intersect_data_scopes():
    user, tenant, platform, store, run, client = _fixture("ops-products-scope")
    _order(tenant, platform, store, run, "visible")
    other = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="other", name="Other", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    _order(tenant, platform, other, run, "other")
    denied = client.get(URL, {"view": "products", "store_id": store.id, "date_from": DAY, "date_to": DAY})
    assert denied.status_code == 403

    _grant(user, "sales_management.skus.view", {"store_ids": [other.id]})
    disjoint = client.get(URL, {"view": "products", "store_id": store.id, "date_from": DAY, "date_to": DAY})
    assert disjoint.status_code == 200
    assert disjoint.json()["data"]["currency_groups"] == []
    assert disjoint.json()["data"]["rows"] == []


@pytest.mark.django_db
def test_exact_product_filter_precedes_pagination_and_returns_full_scope():
    user, tenant, platform, store, run, client = _fixture("ops-exact-product")
    _grant(user, "sales_management.skus.view")
    for suffix in ("first", "target", "last"):
        _order(tenant, platform, store, run, suffix)
    SalesOrderItem.objects.filter(sales_order__external_order_id="target").update(platform_product_id="exact-product")

    result = client.get(URL, {"view": "products", "store_id": store.id, "date_from": DAY,
                              "date_to": DAY, "region": "PH", "platform": "shopee",
                              "currency": "PHP", "product_id": "exact-product", "page": 2}).json()["data"]
    assert [row["product_id"] for row in result["rows"]] == ["exact-product"]
    assert result["page"] == 1
    assert result["has_next"] is False
    assert result["filters"] == {"date_from": DAY, "date_to": DAY, "previous_from": "2026-08-16",
                                 "previous_to": "2026-08-16", "region": "PH", "platform": "shopee",
                                 "store_id": store.id, "currency": "PHP", "view": "products",
                                 "sort": "sales_desc", "status": "all",
                                 "product_id": "exact-product"}


@pytest.mark.django_db
def test_exact_product_filter_rejects_wrong_view_and_repeated_parameter():
    *_, client = _fixture("ops-exact-product-invalid")
    assert client.get(URL, {"view": "stores", "product_id": "P1", "date_from": DAY, "date_to": DAY}).status_code == 400
    assert client.get(URL, {"view": "products", "store_id": "1", "product_id": "P1", "date_from": DAY, "date_to": DAY}).status_code == 400
    assert client.get(f"{URL}?view=products&store_id=1&product_id=P1&product_id=P2&date_from={DAY}&date_to={DAY}").status_code == 400


@pytest.mark.django_db
def test_product_currency_summary_uses_non_cancelled_line_amounts_and_excludes_blank_ids_and_other_tenants():
    user, tenant, platform, store, run, client = _fixture("ops-line-gmv")
    _grant(user, "sales_management.skus.view")
    _order(tenant, platform, store, run, "line-sale", amount="100")
    sale = SalesOrder.objects.get(external_order_id="line-sale")
    SalesOrderItem.objects.filter(sales_order=sale).update(line_total_amount="60")
    _order(tenant, platform, store, run, "cancel-line", amount="500", status="cancelled")
    _order(tenant, platform, store, run, "blank-line", amount="900")
    QuerySet.update(SalesOrderItem.objects.filter(sales_order__external_order_id="blank-line"), platform_product_id="")

    other_user, other_tenant, other_platform, other_store, other_run, _ = _fixture("ops-line-gmv-other-tenant")
    _order(other_tenant, other_platform, other_store, other_run, "tenant-sentinel", amount="999999")
    result = client.get(URL, {"view": "products", "store_id": store.id, "date_from": DAY, "date_to": DAY}).json()["data"]

    assert result["currency_groups"][0]["sales_amount"] == "60"
    assert [row["sales_amount"] for row in result["rows"]] == ["60"]
    assert "tenant-sentinel" not in str(result)
    assert any("已排除" in notice for notice in result["notices"])


@pytest.mark.django_db
def test_product_decline_only_for_strict_over_thirty_percent_yesterday():
    user, tenant, platform, store, run, client = _fixture("ops-diagnosis")
    _grant(user, "sales_management.skus.view")
    yesterday = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1)
    _order(tenant, platform, store, run, "previous", amount="100")
    previous = SalesOrder.objects.get(external_order_id="previous")
    previous.created_at_utc = datetime.combine(yesterday - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    previous.save(update_fields=["created_at_utc"])
    _order(tenant, platform, store, run, "current", amount="69")
    current = SalesOrder.objects.get(external_order_id="current")
    current.created_at_utc = datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC)
    current.save(update_fields=["created_at_utc"])
    SalesOrderItem.objects.filter(sales_order=previous).update(platform_product_id="shared-product")
    SalesOrderItem.objects.filter(sales_order__external_order_id="current").update(platform_product_id="shared-product")
    response = client.get(URL, {"view": "products", "store_id": store.id, "date_from": yesterday.isoformat(), "date_to": yesterday.isoformat()})
    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row["previous_sales_amount"] == "100"
    assert row["change_percent"] == "-31"
    assert row["diagnosis"]["status"] == "suspected_decline"
    assert "买家数" in row["diagnosis"]["missing"]
    assert row["diagnosis"]["steps"][2]["value"] is None


@pytest.mark.django_db
def test_product_missing_baseline_is_null_and_not_classified_as_decline():
    user, tenant, platform, store, run, client = _fixture("ops-no-baseline")
    _grant(user, "sales_management.skus.view")
    _order(tenant, platform, store, run, "current-only", amount="69")
    response = client.get(URL, {"view": "products", "store_id": store.id, "date_from": DAY, "date_to": DAY})
    row = response.json()["data"]["rows"][0]
    assert row["previous_sales_amount"] is None
    assert row["change_percent"] is None
    assert row["diagnosis"] is None


@pytest.mark.django_db
def test_exact_thirty_percent_and_historical_day_do_not_trigger_yesterday_diagnosis():
    user, tenant, platform, store, run, client = _fixture("ops-no-lx-flag")
    _grant(user, "sales_management.skus.view")
    yesterday = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1)
    historical_day = yesterday - timedelta(days=3)
    _order(tenant, platform, store, run, "prev", amount="100")
    previous = SalesOrder.objects.get(external_order_id="prev")
    previous.created_at_utc = datetime.combine(historical_day - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    previous.save(update_fields=["created_at_utc"])
    _order(tenant, platform, store, run, "current", amount="70")
    current = SalesOrder.objects.get(external_order_id="current")
    current.created_at_utc = datetime.combine(historical_day, datetime.min.time(), tzinfo=UTC)
    current.save(update_fields=["created_at_utc"])
    SalesOrderItem.objects.filter(sales_order__in=[previous, current]).update(platform_product_id="shared")
    result = client.get(URL, {"view": "products", "store_id": store.id,
                              "date_from": historical_day.isoformat(), "date_to": historical_day.isoformat()}).json()["data"]
    assert result["rows"][0]["change_percent"] == "-30"
    assert result["rows"][0]["diagnosis"] is None
    assert any("其他历史区间仅展示销售比较" in notice for notice in result["notices"])


@pytest.mark.django_db
def test_sales_operations_rejects_uncompleted_ranges_and_bad_pagination():
    *_, client = _fixture("ops-validation")
    assert client.get(URL, {"date_from": "2026-12-01", "date_to": "2026-12-01"}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "page_size": 51}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "page": 10001}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "page": "١"}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "store_id": "9223372036854775808"}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "store_id": "9" * 5000}).status_code == 400
    assert client.get(URL, {"view": "products", "date_from": DAY, "date_to": DAY}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "sort": "units_desc"}).status_code == 400
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "sort": "unknown"}).status_code == 400
    assert client.get(URL, {"view": "products", "store_id": 1, "date_from": DAY,
                            "date_to": "2026-08-19", "status": "declines"}).status_code == 400


@pytest.mark.django_db
def test_store_summary_query_count_is_constant_as_store_count_grows():
    user, tenant, platform, store, run, client = _fixture("ops-query-count")
    _order(tenant, platform, store, run, "single-store")
    with CaptureQueriesContext(connection) as small_queries:
        small = client.get(URL, {"date_from": DAY, "date_to": DAY})
    for index in range(19):
        extra = StoreMaster.objects.create(
            tenant=tenant, platform=platform, code=f"many-{index}", name=f"Many {index}",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        _order(tenant, platform, extra, run, f"many-sale-{index}")
    with CaptureQueriesContext(connection) as many_queries:
        many = client.get(URL, {"date_from": DAY, "date_to": DAY})
    assert small.status_code == many.status_code == 200
    assert len(small_queries) <= 30
    assert len(many_queries) <= 30
    assert len(many_queries) == len(small_queries)
