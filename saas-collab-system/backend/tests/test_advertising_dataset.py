from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig, ShopeeAdvertisingRecord, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.reports.advertising_dataset import (
    ADVERTISING_DATASET,
    ADVERTISING_FILTERS,
    advertising_queryset,
)
from apps.tenants.models import Tenant
from tests.test_sync_capability_gate import make_job


@pytest.mark.django_db
def test_advertising_dataset_is_tenant_scope_and_shop_daily_limited():
    job, authorization = make_job()
    user, store = job.integration_config.created_by, authorization.store
    permission, _ = Permission.objects.get_or_create(
        code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"},
    )
    role = Role.objects.create(tenant=user.tenant, code="ads-dataset", name="Ads dataset")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"analytics_dimensions": [{"store_id": str(store.pk), "platform": "shopee", "country": "PH"}]},
    )
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="ads-dataset", idempotency_key="ads-dataset")

    def add(kind, key, payload, *, target_store=store, report_date=date(2026, 10, 1), country="PH"):
        return ShopeeAdvertisingRecord.objects.create(
            tenant=job.tenant, store=target_store, source_run=run, kind=kind, record_key=key,
            report_date=report_date, currency="PHP", report_timezone="Asia/Manila",
            dimensions={"store_id": str(target_store.pk), "platform": "shopee", "country": country}, data=payload,
        )

    add("shop_daily", "shop-valid", {"expense": "12.50", "impression": "100", "clicks": "4", "direct_gmv": "20"})
    add("shop_daily", "shop-bad", {"expense": "not-a-number", "impression": None, "broad_gmv": "7"})
    add("shop_hourly", "hourly", {"expense": "900", "impression": "900"})
    add("campaign_daily", "campaign", {"expense": "800", "impression": "800"})
    other_store = StoreMaster.objects.create(
        tenant=job.tenant, platform=store.platform, code="other-shop", name="Other shop", country_code="PH", currency="PHP",
    )
    add("shop_daily", "other-store", {"expense": "600"}, target_store=other_store)
    add("shop_daily", "other-country", {"expense": "500"}, country="MY")
    foreign_tenant = Tenant.objects.create(name="Foreign", code="foreign-ads-dataset")
    foreign_user = CustomUser.objects.create_user(
        username="foreign-ads-dataset", password="not-real", tenant=foreign_tenant, user_type="internal",
    )
    foreign_platform = PlatformMaster.objects.create(
        tenant=foreign_tenant, code="shopee", name="Shopee", platform_type="shopee",
    )
    foreign_store = StoreMaster.objects.create(
        tenant=foreign_tenant, platform=foreign_platform, code="foreign-shop", name="Foreign shop",
        country_code="PH", currency="PHP",
    )
    foreign_config = PlatformIntegrationConfig.objects.create(
        tenant=foreign_tenant, platform="shopee", account_alias="foreign-ads", created_by=foreign_user,
    )
    foreign_job = SyncJob.objects.create(
        tenant=foreign_tenant, integration_config=foreign_config, resource_type=SyncJob.ResourceType.SALES_ORDER,
    )
    foreign_run = SyncRun.objects.create(
        tenant=foreign_job.tenant, sync_job=foreign_job, run_id="foreign-ads", idempotency_key="foreign-ads",
    )
    ShopeeAdvertisingRecord.objects.create(
        tenant=foreign_job.tenant, store=foreign_store, source_run=foreign_run, kind="shop_daily",
        record_key="foreign-tenant", report_date=date(2026, 10, 1), currency="PHP",
        report_timezone="Asia/Manila", dimensions={"store_id": str(foreign_store.pk), "platform": "shopee", "country": "PH"},
        data={"expense": "700"},
    )

    queryset = advertising_queryset(
        SimpleNamespace(user=user), {"date_from": "2026-10-01", "date_to": "2026-10-01"}, "analytics.view",
    )
    rows = queryset.filter(record_key="shop-valid").aggregate(**{
        key: ADVERTISING_DATASET["metrics"][key]["source"]
        for key in ("expense", "impressions", "clicks", "direct_gmv", "broad_gmv")
    })
    incomplete = queryset.aggregate(**{
        key: ADVERTISING_DATASET["metrics"][key]["source"]
        for key in ("expense", "impressions", "clicks", "direct_gmv", "broad_gmv")
    })
    assert queryset.count() == 2
    assert Decimal(str(rows["expense"])) == Decimal("12.5")
    assert str(rows["impressions"]) == "100"
    assert str(rows["clicks"]) == "4"
    assert str(rows["direct_gmv"]) == "20"
    assert rows["broad_gmv"] is None
    assert Decimal(str(incomplete["expense"])) == Decimal("12.5")
    assert {key: value for key, value in incomplete.items() if key != "expense"} == {
        "impressions": 100, "clicks": 4, "direct_gmv": 20, "broad_gmv": 7,
    }
    assert "暂估" in ADVERTISING_DATASET["note"]
    assert "currency" in ADVERTISING_DATASET["defaults"]["dimensions"]
    assert "region" in ADVERTISING_FILTERS and "platforms" in ADVERTISING_FILTERS and "store_ids" in ADVERTISING_FILTERS


@pytest.mark.django_db
def test_advertising_dataset_rejects_unbounded_or_invalid_date_ranges():
    job, _ = make_job()
    request = SimpleNamespace(user=job.integration_config.created_by)
    with pytest.raises(ValidationError):
        advertising_queryset(request, {"date_from": "2026-10-01"}, "analytics.view")
    with pytest.raises(ValidationError):
        advertising_queryset(request, {"date_from": "2024-01-01", "date_to": "2026-10-01"}, "analytics.view")
    with pytest.raises(ValidationError):
        advertising_queryset(request, {"date_from": "2026-10-02", "date_to": "2026-10-01"}, "analytics.view")


@pytest.fixture
def scoped_advertising_selection(db):
    job, authorization = make_job()
    user = job.integration_config.created_by
    stores = [authorization.store]
    for code, country in (("selected", "PH"), ("unselected", "PH"), ("denied", "PH"), ("malaysia", "MY")):
        stores.append(StoreMaster.objects.create(tenant=user.tenant, platform=stores[0].platform,
            code=code, name=code, country_code=country, currency="PHP"))
    permission, _ = Permission.objects.get_or_create(code="analytics.view",
        defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    role = Role.objects.create(tenant=user.tenant, code="ads-selection", name="Ads selection")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    allowed = [store for index, store in enumerate(stores) if index != 3]
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type="custom", config={
        "analytics_dimensions": [{"store_id": str(store.pk), "platform": "shopee", "country": store.country_code} for store in allowed]})
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="ads-selection", idempotency_key="ads-selection")
    for store in stores:
        ShopeeAdvertisingRecord.objects.create(tenant=job.tenant, store=store, source_run=run,
            kind="shop_daily", record_key=f"selection-{store.pk}", report_date=date(2026, 10, 1), currency="PHP",
            report_timezone="Asia/Manila", dimensions={"store_id": str(store.pk), "platform": "shopee", "country": store.country_code},
            data={"expense": "10"})
    return SimpleNamespace(user=user), stores, allowed


@pytest.mark.parametrize("platforms", ["shopee,lazada", "lazada,shopee", ["lazada", "shopee"], " SHOPEE , lazada "])
def test_advertising_mixed_platform_selection_keeps_matching_scoped_facts(scoped_advertising_selection, platforms):
    request, _, allowed = scoped_advertising_selection
    rows = advertising_queryset(request, {"date_from": "2026-10-01", "date_to": "2026-10-01", "platforms": platforms}, "analytics.view")
    assert set(rows.values_list("store_id", flat=True)) == {store.pk for store in allowed}
    assert not advertising_queryset(request, {"date_from": "2026-10-01", "date_to": "2026-10-01", "platforms": "lazada"}, "analytics.view").exists()
    assert not advertising_queryset(request, {"date_from": "2026-10-01", "date_to": "2026-10-01", "platform": "lazada", "platforms": "shopee"}, "analytics.view").exists()


@pytest.mark.parametrize("country_key", ["country", "storecountry", "region"])
def test_advertising_detail_preserves_multivalue_filters_inside_permissions(scoped_advertising_selection, country_key):
    request, stores, _ = scoped_advertising_selection
    selected = ",".join(str(stores[index].pk) for index in (0, 1, 3, 4))
    filters = {"store_ids": selected, "platforms": "shopee,lazada", country_key: "PH", "currency": "PHP"}
    aggregate = advertising_queryset(request, {**filters, "date_from": "2026-10-01", "date_to": "2026-10-01"}, "analytics.view")
    expected = {stores[0].pk, stores[1].pk}
    assert set(aggregate.values_list("store_id", flat=True)) == expected
    client = APIClient()
    client.force_authenticate(request.user)
    response = client.get("/api/internal/analytics/advertising/", {**filters,
        "kind": "shop_daily", "period_start": "2026-10-01", "period_end": "2026-10-01"})
    assert response.status_code == 200
    assert {row["store_id"] for row in response.data["data"]["results"]} == expected
    assert response.data["data"]["count"] == 2
    assert client.get("/api/internal/analytics/advertising/", {**filters, "unknown": "bad"}).status_code == 400


@pytest.mark.parametrize("store_ids", ["abc", "0", "-1", ",", "1,,2", "9223372036854775808", "9" * 5000])
def test_advertising_multistore_filter_rejects_invalid_values(scoped_advertising_selection, store_ids):
    request, _, _ = scoped_advertising_selection
    with pytest.raises(ValidationError):
        advertising_queryset(request, {"date_from": "2026-10-01", "date_to": "2026-10-01", "store_ids": store_ids}, "analytics.view")
    client = APIClient()
    client.force_authenticate(request.user)
    assert client.get("/api/internal/analytics/advertising/", {"store_ids": store_ids}).status_code == 400
