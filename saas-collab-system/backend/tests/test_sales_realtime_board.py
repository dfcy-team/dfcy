from datetime import UTC, datetime

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
    auth = PlatformIntegrationConfig.objects.get(tenant=tenant)
    ad_job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="advertising_report")
    ad_run = SyncRun.objects.create(
        tenant=tenant, sync_job=ad_job, run_id="ad-run", idempotency_key="ad-key",
        status=SyncRun.Status.SUCCESS,
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, kind="shop_daily", record_key=f"shop_daily:{DAY}",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(store.id), "platform": "shopee"}, data={"expense": "10.50"},
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=no_sales_store, kind="shop_daily", record_key=f"shop_daily:{DAY}:ads-only",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=ad_run,
        dimensions={"store_id": str(no_sales_store.id), "platform": "shopee"}, data={"expense": "1.00"},
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]

    assert group["ad_spend"] == "11.5"
    assert group["ad_rate"] == "5.75"
    assert group["ad_status"] == "reference_unverified"
    assert group["ad_coverage"] == {
        "covered_store_count": 2, "expected_store_count": 2,
        "covered_day_count": 1, "expected_day_count": 1,
    }
    assert group["ad_rate_sales_amount"] == group["sales_amount"] == "200"


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
