from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig, ShopeeAdvertisingRecord, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.sales_management.services import upsert_normalized_order
from apps.tenants.models import Tenant


URL = "/api/internal/commerce/realtime-board/"
DAY = "2026-08-17"


def _grant(user, code, config=None):
    permission, _ = Permission.objects.get_or_create(
        code=code, defaults={"name": code, "module": "sales_management", "action": "view"}
    )
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}-{Role.objects.filter(tenant=user.tenant).count()}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant, role=role,
        scope_type=DataScope.ScopeType.CUSTOM if config else DataScope.ScopeType.ALL,
        config=config or {},
    )


def _fixture(suffix):
    tenant = Tenant.objects.create(name=suffix, code=suffix)
    user = CustomUser.objects.create_user(username=f"board-{suffix}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    _grant(user, "sales_management.view")
    platform = PlatformMaster.objects.create(tenant=tenant, code=f"p-{suffix}", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code=f"s-{suffix}", name=f"Store {suffix}", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    auth = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="shopee", account_alias=f"auth-{suffix}", created_by=user
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="sales_order")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id=f"run-{suffix}", idempotency_key=f"key-{suffix}")
    client = APIClient()
    client.force_authenticate(user=user)
    return user, tenant, platform, store, run, client


def _order(tenant, platform, store, run, suffix, *, currency="PHP", amount="100.00", status="completed"):
    return upsert_normalized_order(
        tenant=tenant, source_run=run,
        payload={
            "contract_version": "1.0", "store_id": store.id, "external_order_id": suffix,
            "region": "PH", "raw_status": status.upper(), "normalized_status": status,
            "created_at_utc": datetime(2026, 8, 17, 8, 0, tzinfo=UTC).isoformat(),
            "updated_at_utc": datetime(2026, 8, 17, 8, 0, tzinfo=UTC).isoformat(),
            "currency": currency, "order_total_amount": amount,
            "lines": [{"external_line_id": f"line-{suffix}", "platform_product_id": f"product-{suffix}",
                       "seller_sku": f"sku-{suffix}", "item_name_snapshot": f"Item {suffix}",
                       "quantity": 2, "sale_unit_price": str(float(amount) / 2),
                       "line_total_amount": amount, "currency": currency}],
        },
    )


@pytest.mark.django_db
def test_realtime_board_groups_amounts_by_currency_and_excludes_cancelled_sales():
    user, tenant, platform, store, run, client = _fixture("board-currency")
    _order(tenant, platform, store, run, "php", amount="100.25")
    _order(tenant, platform, store, run, "cancelled", amount="900", status="cancelled")
    _order(tenant, platform, store, run, "thb", currency="THB", amount="50")

    response = client.get(URL, {"date_from": DAY, "date_to": DAY})

    assert response.status_code == 200
    groups = {row["currency"]: row for row in response.json()["data"]["currency_groups"]}
    assert groups["PHP"]["sales_amount"] == "100.25"
    assert groups["PHP"]["order_count"] == 2
    assert groups["PHP"]["valid_order_count"] == 1
    assert groups["PHP"]["units_sold"] == 2
    assert groups["THB"]["sales_amount"] == "50"


@pytest.mark.django_db
def test_hourly_ads_are_separate_scoped_observations_with_real_gaps_and_zero_values():
    user, tenant, platform, store, run, client = _fixture("board-hourly-ads")
    _order(tenant, platform, store, run, "hourly-sale")
    _grant(user, "analytics.view", {"analytics_dimensions": [{"platform": "shopee", "store_id": str(store.id)}]})
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant, platform="shopee")
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(tenant=tenant, sync_job=ad_job, run_id="hourly-ads", idempotency_key="hourly-ads-key")
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"daily:{DAY}", report_date=DAY,
        currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "99", "clicks": 99},
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_hourly", record_key=f"hourly:{DAY}:0", report_date=DAY,
        currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"hour": 0, "expense": "0", "clicks": 0},
    )
    response = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]

    assert response["ad_spend"] == "99"
    assert response["hourly_advertising"] == {
        "date": DAY, "observed_expense": "0", "observed_clicks": 0,
        "observed_store_count": 1, "observed_store_hour_count": 1,
        "timezones": ["Asia/Manila"], "coverage_status": "observed_only_unknown",
        "hours": [{"hour": 0, "label": "00:00", "expense": "0", "clicks": 0, "observed_store_count": 1}],
    }


@pytest.mark.django_db
def test_realtime_board_empty_data_and_unverified_ads_are_explicit():
    user, tenant, platform, store, run, client = _fixture("board-empty")
    empty = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    assert empty["currency_groups"] == []

    _order(tenant, platform, store, run, "sale")
    no_ads_permission = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    assert no_ads_permission["ad_spend"] is None
    assert no_ads_permission["ad_status"] == "permission_missing"
    _grant(user, "analytics.view")
    data = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    group = data["currency_groups"][0]
    assert group["ad_spend"] is None
    assert group["ad_rate"] is None
    assert group["ad_status"] == "unavailable"
    assert group["ad_coverage"]["expected_day_count"] == 1


@pytest.mark.django_db
def test_realtime_board_calculates_ads_reference_for_historical_coverage():
    user, tenant, platform, store, run, client = _fixture("board-ads-complete")
    _order(tenant, platform, store, run, "sale", amount="200")
    no_sales_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="ads-only", name="Ads only", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    _grant(user, "analytics.view", {"analytics_dimensions": [
        {"platform": "shopee", "store_id": str(store.id)},
        {"platform": "shopee", "store_id": str(no_sales_store.id)},
    ]})
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant, platform="shopee")
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="ad-run", idempotency_key="ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10.50", "clicks": 0},
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=no_sales_store, kind="shop_daily", record_key=f"shop_daily:{DAY}:ads-only",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(no_sales_store.id), "platform": "shopee"}, data={"expense": "1.00", "clicks": 7},
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]

    assert group["ad_spend"] == "11.5"
    assert group["ad_clicks"] == 7
    assert group["ad_clicks_observed_count"] == 2
    assert group["ad_clicks_partial"] is False
    assert group["ad_rate"] == "5.75"
    assert group["ad_status"] == "reference_unverified"
    assert group["ad_coverage"] == {
        "covered_store_count": 2, "expected_store_count": 2,
        "covered_day_count": 1, "expected_day_count": 1,
    }
    assert group["ad_rate_sales_amount"] == group["sales_amount"] == "200"
    assert group["store_roi"] == str(Decimal("200") / Decimal("11.5"))


@pytest.mark.django_db
def test_realtime_board_estimates_roi_from_observed_expense_when_daily_facts_are_partial():
    user, tenant, platform, store, run, client = _fixture("board-ads-partial")
    _order(tenant, platform, store, run, "sale", amount="200")
    _grant(user, "analytics.view")
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant, platform="shopee")
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="partial-ad-run", idempotency_key="partial-ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}:observed",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10", "clicks": 12},
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}:missing-expense",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={},
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]

    assert group["ad_spend"] == "10"
    assert group["ad_rate"] == "5"
    assert group["store_roi"] == "20"
    assert group["ad_status"] == "estimated"
    assert group["ad_clicks"] == 12
    assert group["ad_clicks_observed_count"] == 1
    assert group["ad_clicks_partial"] is True
    assert "暂估" in group["ad_reason"] and "尚未拉取" in group["ad_reason"]


@pytest.mark.django_db
def test_mixed_platform_currency_uses_authorized_shopee_sales_for_roi_numerator():
    user, tenant, platform, store, run, client = _fixture("board-mixed-platform-roi")
    _order(tenant, platform, store, run, "shopee-sale", amount="100")
    unauthorized_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="unauthorized-shopee", name="Unauthorized Shopee",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    _order(tenant, platform, unauthorized_store, run, "unauthorized-sale", amount="50")
    other_platform = PlatformMaster.objects.create(
        tenant=tenant, code="lazada-mixed", name="Lazada", platform_type="lazada"
    )
    other_store = StoreMaster.objects.create(
        tenant=tenant, platform=other_platform, code="lazada-store", name="Lazada Store",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    lazada_auth = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="lazada", account_alias="lazada-mixed-auth", created_by=user
    )
    lazada_job = SyncJob.objects.create(tenant=tenant, integration_config=lazada_auth, resource_type="sales_order")
    lazada_run = SyncRun.objects.create(
        tenant=tenant, sync_job=lazada_job, run_id="lazada-mixed-run", idempotency_key="lazada-mixed-key"
    )
    _order(tenant, other_platform, other_store, lazada_run, "lazada-sale", amount="200")
    _grant(user, "analytics.view", {"analytics_dimensions": [{"platform": "shopee", "store_id": str(store.id)}]})
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant, platform="shopee")
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="mixed-roi-ad-run", idempotency_key="mixed-roi-ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"mixed-shop-daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10"},
    )
    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    assert group["sales_amount"] == "350"
    assert group["ad_rate_sales_amount"] == "100"
    assert group["ad_rate"] == "10"
    assert group["store_roi"] == "10"
    assert "Shopee" in group["ad_rate_platform_scope"]


@pytest.mark.django_db
def test_board_region_filters_by_store_country_and_returns_country_on_store_ranking():
    user, tenant, platform, store, run, client = _fixture("board-region-filter")
    _order(tenant, platform, store, run, "ph-sale")
    other_country = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="my-store", name="Malaysia Store", country_code="MY",
        currency="PHP", timezone="Asia/Kuala_Lumpur",
    )
    _order(tenant, platform, other_country, run, "my-sale")
    from apps.commerce.models import SalesOrder
    SalesOrder.objects.filter(store=other_country).update(region="MY")

    response = client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "ph"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filters"]["region"] == "PH"
    ranking = data["currency_groups"][0]["store_ranking"]
    assert [row["country_code"] for row in ranking] == ["PH"]
    assert client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "Philippines!"}).status_code == 400


@pytest.mark.django_db
def test_board_region_filter_respects_sales_store_scope():
    user, tenant, platform, store, run, client = _fixture("board-region-scope")
    _order(tenant, platform, store, run, "ph-visible")
    hidden = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="my-store", name="Malaysia Store", country_code="MY",
        currency="PHP", timezone="Asia/Kuala_Lumpur",
    )
    _order(tenant, platform, hidden, run, "my-hidden")
    DataScope.objects.filter(role__user_roles__user=user, role__permissions__code="sales_management.view").delete()
    _grant(user, "sales_management.view", {"regions": ["PH"]})

    allowed = client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "PH"})
    assert allowed.status_code == 200
    assert allowed.json()["data"]["currency_groups"][0]["store_ranking"][0]["country_code"] == "PH"
    response = client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "MY"})
    assert response.status_code == 200
    assert response.json()["data"]["currency_groups"] == []


@pytest.mark.django_db
def test_board_roi_is_null_for_zero_ad_spend_with_complete_coverage():
    user, tenant, platform, store, run, client = _fixture("board-zero-ads-roi")
    _order(tenant, platform, store, run, "sale", amount="200")
    _grant(user, "analytics.view")
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant)
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="zero-ad-run", idempotency_key="zero-ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "0"},
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]

    assert group["ad_status"] == "reference_unverified"
    assert group["ad_rate"] == "0"
    assert group["store_roi"] is None


@pytest.mark.django_db
def test_board_disables_ad_metrics_when_order_region_conflicts_with_store_country():
    user, tenant, platform, store, run, client = _fixture("board-country-conflict")
    _order(tenant, platform, store, run, "ph-sale", amount="100")
    _order(tenant, platform, store, run, "my-sale", amount="100")
    from apps.commerce.models import SalesOrder
    SalesOrder.objects.filter(tenant=tenant, external_order_id="my-sale").update(region="MY")
    _grant(user, "analytics.view")
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant)
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="conflict-ad-run", idempotency_key="conflict-ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10"},
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "PH"}).json()["data"]["currency_groups"][0]

    assert group["sales_amount"] == "100"
    assert group["ad_spend"] == "10"
    assert group["ad_rate"] is None
    assert group["store_roi"] is None
    assert group["ad_status"] == "unavailable"
    assert "订单国家与店铺国家不一致" in group["ad_reason"]


@pytest.mark.django_db
def test_board_detects_country_conflict_hidden_by_region_filter_when_selected_order_cancelled():
    user, tenant, platform, store, run, client = _fixture("board-country-conflict-cancelled")
    _order(tenant, platform, store, run, "ph-cancelled", status="cancelled")
    _order(tenant, platform, store, run, "my-sale", amount="100")
    from apps.commerce.models import SalesOrder
    SalesOrder.objects.filter(tenant=tenant, external_order_id="my-sale").update(region="MY")
    _grant(user, "analytics.view")
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant)
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="conflict-cancelled-ad-run",
        idempotency_key="conflict-cancelled-ad-key", status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10"},
    )

    response = client.get(URL, {"date_from": DAY, "date_to": DAY, "region": "PH"})
    assert response.status_code == 200
    group = response.json()["data"]["currency_groups"][0]

    assert group["sales_amount"] == "0"
    assert group["ad_spend"] == "10"
    assert group["ad_rate"] is None
    assert group["store_roi"] is None
    assert group["ad_status"] == "unavailable"


@pytest.mark.django_db
def test_realtime_board_rejects_oversized_range_and_applies_store_scope():
    user, tenant, platform, store, run, client = _fixture("board-scope")
    hidden = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="hidden", name="Hidden", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    _order(tenant, platform, hidden, run, "hidden")
    DataScope.objects.filter(role__user_roles__user=user, role__permissions__code="sales_management.view").delete()
    _grant(user, "sales_management.view", {"store_ids": [store.id]})

    scoped = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    assert scoped["currency_groups"] == []
    oversized = client.get(URL, {"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert oversized.status_code == 400


@pytest.mark.django_db
def test_realtime_board_uses_bounded_query_count():
    user, tenant, platform, store, run, client = _fixture("board-query-count")
    for index in range(12):
        _order(tenant, platform, store, run, f"order-{index}")

    with CaptureQueriesContext(connection) as queries:
        response = client.get(URL, {"date_from": DAY, "date_to": DAY})

    assert response.status_code == 200
    assert len(queries) <= 24


@pytest.mark.django_db
def test_board_rejects_unshared_filter_aliases_and_repeated_parameters():
    *_, client = _fixture("board-filter-alias")
    for key in ("store_ids", "platforms", "region", "country"):
        assert client.get(URL, {"date_from": DAY, "date_to": DAY, key: "1"}).status_code == 400
    assert client.get(URL + "?store_id=1&store_id=2").status_code == 400


@pytest.mark.django_db
def test_board_merges_seller_aliases_for_same_internal_sku_before_ranking():
    from apps.commerce.models import SalesOrderItem
    from apps.products.models import ProductSKU, ProductSPU

    user, tenant, platform, store, run, client = _fixture("board-sku-alias")
    _order(tenant, platform, store, run, "alias-a", amount="30")
    _order(tenant, platform, store, run, "alias-b", amount="70")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="BOARD-SPU", product_name="Board product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="BOARD-SKU")
    SalesOrderItem.objects.filter(sales_order__tenant=tenant).update(internal_sku=sku)
    response = client.get(URL, {"date_from": DAY, "date_to": DAY})
    assert response.status_code == 200
    ranking = response.json()["data"]["currency_groups"][0]["sku_ranking"]
    assert len(ranking) == 1
    assert ranking[0]["sku"] == "BOARD-SKU"
    assert ranking[0]["sales_amount"] == "100"
    assert ranking[0]["units_sold"] == 4


@pytest.mark.django_db
def test_ranking_switches_select_top_ten_from_full_dataset_not_sales_subset():
    from apps.commerce.models import SalesOrderItem

    user, tenant, platform, low_store, run, client = _fixture("board-ranking-switch")
    for index in range(4):
        _order(tenant, platform, low_store, run, f"low-{index}", amount="1")
    SalesOrderItem.objects.filter(sales_order__store=low_store).update(seller_sku="LOW-PRICE-HIGH-VOLUME")
    for index in range(10):
        store = StoreMaster.objects.create(
            tenant=tenant, platform=platform, code=f"rank-{index}", name=f"Rank {index}",
            country_code="PH", currency="PHP", timezone="Asia/Manila",
        )
        _order(tenant, platform, store, run, f"high-{index}", amount=str(100 + index))
    response = client.get(URL, {"date_from": DAY, "date_to": DAY})
    assert response.status_code == 200
    group = response.json()["data"]["currency_groups"][0]
    assert low_store.id not in {row["store_id"] for row in group["store_ranking"]}
    assert group["store_rankings"]["order_count"][0]["store_id"] == low_store.id
    assert group["store_rankings"]["order_count"][0]["order_count"] == 4
    assert "LOW-PRICE-HIGH-VOLUME" not in {row["sku"] for row in group["sku_ranking"]}
    assert group["sku_rankings"]["units_sold"][0]["sku"] == "LOW-PRICE-HIGH-VOLUME"
    assert group["sku_rankings"]["units_sold"][0]["units_sold"] == 8
    for collection in (group["store_rankings"], group["sku_rankings"]):
        assert all(len(rows) == 10 for rows in collection.values())


@pytest.mark.django_db
def test_full_board_attaches_shared_stock_and_does_not_revive_unmapped_latest_snapshot():
    from datetime import timedelta
    from django.utils import timezone
    from apps.commerce.models import InventorySnapshot, SalesOrderItem
    from apps.masterdata.models import WarehouseMaster
    from apps.products.models import ProductSKU, ProductSPU

    user, tenant, platform, store, run, client = _fixture("board-stock-integration")
    _order(tenant, platform, store, run, "stock-sale", amount="100")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="STOCK-SPU", product_name="Stock product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="STOCK-SKU", inventory_type="physical")
    SalesOrderItem.objects.filter(sales_order__tenant=tenant).update(internal_sku=sku)
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="stock-wh", name="共享仓", country_code="PH", warehouse_type="owned")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="jifeng_wms", account_alias="stock", created_by=user)
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="inventory_snapshot")
    stock_run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="stock-run", idempotency_key="stock-key", status="success")
    now = timezone.now()
    common = dict(tenant=tenant, site_code="PH", warehouse=warehouse, source_run=stock_run, source_sku="warehouse-source", on_hand_qty=20, available_qty=12, provided_quantity_fields=["available_qty"], payload_hash="d" * 64)
    InventorySnapshot.objects.create(**common, internal_sku=sku, snapshot_at_utc=now - timedelta(hours=1))
    response = client.get(URL, {"date_from": DAY, "date_to": DAY})
    assert response.status_code == 200
    group = response.json()["data"]["currency_groups"][0]
    assert group["sku_ranking"][0]["inventory"]["available_qty"] == 12
    assert group["sku_rankings"]["units_sold"][0]["inventory"]["available_qty"] == 12
    assert group["sku_ranking"][0]["inventory"]["coverage_days"] is None
    assert "共享" in group["sku_ranking"][0]["inventory"]["basis"]
    InventorySnapshot.objects.create(**common, internal_sku=None, snapshot_at_utc=now - timedelta(minutes=30))
    refreshed = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    assert refreshed["currency_groups"][0]["sku_ranking"][0]["inventory"]["available_qty"] is None


@pytest.mark.django_db
def test_inventory_database_read_failure_preserves_sales_response():
    from unittest.mock import patch
    from django.db import OperationalError

    user, tenant, platform, store, run, client = _fixture("board-stock-failure")
    _order(tenant, platform, store, run, "stock-failure-sale", amount="100")
    with patch("apps.sales_management.board_inventory.attach_board_inventory", side_effect=OperationalError("synthetic inventory timeout")):
        response = client.get(URL, {"date_from": DAY, "date_to": DAY})
    assert response.status_code == 200
    group = response.json()["data"]["currency_groups"][0]
    assert group["sales_amount"] == "100"
    assert group["sku_ranking"][0]["inventory"]["available_qty"] is None
    assert group["sku_ranking"][0]["inventory"]["label"] == "库存读取暂不可用"


@pytest.mark.django_db
def test_today_trend_uses_local_hours_and_previous_day_comparison():
    from unittest.mock import patch
    from datetime import date
    from apps.commerce.models import SalesOrder
    _, tenant, platform, store, run, client = _fixture("hourly-trend")
    _order(tenant, platform, store, run, "today", amount="100")
    old = _order(tenant, platform, store, run, "previous", amount="40")
    SalesOrder.objects.filter(pk=old.pk).update(created_at_utc=datetime(2026,8,16,8,tzinfo=UTC))
    with patch("apps.sales_management.realtime_board.timezone.localdate", return_value=date(2026,8,17)):
        result = client.get(URL, {"date_from": DAY,"date_to": DAY})
    assert result.status_code == 200
    group=result.json()["data"]["currency_groups"][0]
    assert group["trend_granularity"] == "hour"
    assert group["trend"] == [{"date":"16:00","sales_amount":"100","order_count":1}]
    assert group["previous_hourly_trend"] == [{"date":"16:00","sales_amount":"40","order_count":1}]
    assert group["recent_trend"][0]["date"] == "2026-08-16"
    assert group["sales_amount"] == "100"
