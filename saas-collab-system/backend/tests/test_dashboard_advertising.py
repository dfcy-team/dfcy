from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.integrations.models import (
    PlatformIntegrationConfig,
    ShopeeAdvertisingRecord,
    TikTokAdsAdvertiserMapping,
    TikTokAdsDailySpend,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.sales_management.dashboard_advertising import dashboard_advertising
from tests.test_sales_realtime_board import _fixture, _grant


START = date(2026, 10, 1)
END = date(2026, 10, 2)


def _store_row(store, currency=None):
    return {"id": store.pk, "currency": currency or store.currency, "timezone": store.timezone,
            "platform__platform_type": store.platform.platform_type, "country_code": store.country_code}


def _stores(*stores):
    return {store.pk: _store_row(store) for store in stores}


def _shopee_fact(tenant, store, run, key, day, currency, expense, tz="Asia/Manila"):
    return ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, source_run=run, kind="shop_daily", record_key=key,
        report_date=day, currency=currency, report_timezone=tz,
        dimensions={"store_id": str(store.pk), "platform": "shopee", "country": store.country_code},
        data={"expense": expense},
    )


def _grant_custom(user, code, config):
    permission, _ = Permission.objects.get_or_create(
        code=code, defaults={"name": code, "module": code.split(".")[0], "action": "view",
                             "permission_type": "action"},
    )
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.pk}-{Role.objects.count()}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    return DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM, config=config)


def _tiktok_mapping(user, store, advertiser="100", currency="PHP", timezone="Asia/Manila"):
    config = PlatformIntegrationConfig.objects.create(
        tenant=user.tenant, platform="tiktok", account_alias=f"ads-{advertiser}", created_by=user,
        environment="pilot", platform_config={"api_type": "advertising"},
    )
    return TikTokAdsAdvertiserMapping.objects.create(
        tenant=user.tenant, store=store, integration_config=config, advertiser_id=advertiser,
        token_id="tok_" + str(advertiser).zfill(32), currency=currency, timezone=timezone,
    )


@pytest.mark.django_db
def test_requires_analytics_permission_before_reading_facts(monkeypatch):
    user, tenant, _, store, run, _ = _fixture("dashboard-ad-forbidden")
    monkeypatch.setattr("apps.sales_management.dashboard_advertising.advertising_queryset",
                        lambda *a, **kw: pytest.fail("facts queried before analytics permission"))
    status, data = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, END)
    assert (status, data) == ("forbidden", {})


@pytest.mark.django_db
def test_shopee_total_requires_every_store_and_day_and_rejects_ambiguous_rows():
    user, tenant, platform, store, run, _ = _fixture("dashboard-ad-complete")
    _grant(user, "analytics.view")
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code="missing", name="Missing",
                                       country_code="PH", currency="PHP", timezone="Asia/Manila")
    _shopee_fact(tenant, store, run, "one", START, "PHP", "4.25")
    _shopee_fact(tenant, store, run, "duplicate-a", END, "PHP", "2")
    _shopee_fact(tenant, store, run, "duplicate-b", END, "PHP", "3")
    _shopee_fact(tenant, other, run, "other-end", END, "PHP", "1")
    status, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store, other), START, END)
    assert status == "available"
    assert result[("PHP", START.isoformat())] is None  # other selected store has no fact
    assert result[("PHP", END.isoformat())] is None  # duplicate rows are ambiguous


@pytest.mark.django_db
def test_comparison_uses_only_shared_complete_stores_and_keeps_currency_isolated():
    user, tenant, platform, a, run, _ = _fixture("dashboard-ad-common-comparison")
    _grant(user, "analytics.view")
    b = StoreMaster.objects.create(tenant=tenant, platform=platform, code="b", name="B",
                                   country_code="PH", currency="PHP", timezone="Asia/Manila")
    usd = StoreMaster.objects.create(tenant=tenant, platform=platform, code="usd", name="USD",
                                     country_code="US", currency="USD", timezone="Asia/Manila")
    # A and B overlap both days; USD is a separate currency cohort.
    for store, day, value in ((a, START, "2"), (a, END, "0"), (b, START, "3"), (b, END, "4"),
                              (usd, START, "7"), (usd, END, "8")):
        _shopee_fact(tenant, store, run, f"{store.pk}-{day}", day, store.currency, value)
    status, strict, comparison_map = dashboard_advertising(
        SimpleNamespace(user=user), _stores(a, b, usd), START, END, comparison=True,
    )
    assert status == "available"
    assert strict[("PHP", END.isoformat())] == Decimal("4")
    assert comparison_map[("PHP", END.isoformat())] == {
        "current": "4", "previous": "5", "covered_stores": 2, "total_stores": 2,
    }
    assert comparison_map[("USD", END.isoformat())] == {
        "current": "8", "previous": "7", "covered_stores": 1, "total_stores": 1,
    }


@pytest.mark.django_db
def test_comparison_with_no_common_store_is_null_and_zero_baseline_is_preserved():
    user, tenant, platform, a, run, _ = _fixture("dashboard-ad-no-common-comparison")
    _grant(user, "analytics.view")
    b = StoreMaster.objects.create(tenant=tenant, platform=platform, code="b", name="B",
                                   country_code="PH", currency="PHP", timezone="Asia/Manila")
    _shopee_fact(tenant, a, run, "only-yesterday", START, "PHP", "6")
    _shopee_fact(tenant, b, run, "only-today", END, "PHP", "9")
    _, _, no_common = dashboard_advertising(SimpleNamespace(user=user), _stores(a, b), START, END, comparison=True)
    assert no_common[("PHP", END.isoformat())] is None
    _shopee_fact(tenant, a, run, "today-zero", END, "PHP", "0")
    _, _, zero_base = dashboard_advertising(SimpleNamespace(user=user), _stores(a), START, END, comparison=True)
    assert zero_base[("PHP", END.isoformat())] == {
        "current": "0", "previous": "6", "covered_stores": 1, "total_stores": 1,
    }


@pytest.mark.django_db
def test_shopee_preserves_explicit_zero_and_currency_isolation():
    user, tenant, platform, store, run, _ = _fixture("dashboard-ad-zero")
    _grant(user, "analytics.view")
    usd = StoreMaster.objects.create(tenant=tenant, platform=platform, code="usd", name="USD",
                                     country_code="US", currency="USD", timezone="Asia/Manila")
    _shopee_fact(tenant, store, run, "php-zero", START, "PHP", "0")
    _shopee_fact(tenant, usd, run, "usd-spend", START, "USD", "8.50")
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store, usd), START, START)
    assert result[("PHP", START.isoformat())] == Decimal("0")
    assert result[("USD", START.isoformat())] == Decimal("8.50")


@pytest.mark.django_db
def test_tiktok_requires_both_permissions_and_complete_matching_mapping_days():
    user, tenant, _, _, _, _ = _fixture("dashboard-ad-tiktok")
    _grant(user, "analytics.view")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="tk1", name="TikTok shop",
                                       country_code="PH", currency="PHP", timezone="Asia/Manila")
    mapping = _tiktok_mapping(user, store)
    _, denied = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, END)
    assert denied[("PHP", START.isoformat())] is None
    _grant(user, "integrations.store.view")
    TikTokAdsDailySpend.objects.create(tenant=tenant, mapping=mapping, date=START, spend="0", currency="PHP")
    status, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, END)
    assert status == "available"
    assert result[("PHP", START.isoformat())] == Decimal("0")
    assert result[("PHP", END.isoformat())] is None


@pytest.mark.django_db
def test_tiktok_currency_mismatch_and_invisible_mapping_cannot_be_partially_summed():
    user, tenant, _, _, _, _ = _fixture("dashboard-ad-tiktok-scope")
    _grant(user, "analytics.view")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="tk1", name="TikTok shop",
                                       country_code="PH", currency="PHP", timezone="Asia/Manila")
    mapping = _tiktok_mapping(user, store)
    _grant_custom(user, "integrations.store.view", {
        "integration_config_ids": [mapping.integration_config_id],
    })
    TikTokAdsDailySpend.objects.create(tenant=tenant, mapping=mapping, date=START, spend="9", currency="USD")
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None

    hidden = _tiktok_mapping(user, store, advertiser="101")
    fact = TikTokAdsDailySpend.objects.get(mapping=mapping, date=START)
    fact.currency = "PHP"
    fact.save(update_fields=["currency"])
    mapping.timezone = "UTC"
    mapping.save(update_fields=["timezone"])
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None
    mapping.timezone = "Asia/Manila"
    mapping.save(update_fields=["timezone"])
    TikTokAdsDailySpend.objects.create(tenant=tenant, mapping=hidden, date=START, spend="1", currency="PHP")
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None


@pytest.mark.django_db
def test_tiktok_reuses_shared_integration_scope_validation():
    user, tenant, _, _, _, _ = _fixture("dashboard-ad-tiktok-validation")
    _grant(user, "analytics.view")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="tk1", name="TikTok shop",
                                       country_code="PH", currency="PHP", timezone="Asia/Manila")
    mapping = _tiktok_mapping(user, store)
    scope = _grant_custom(user, "integrations.store.view", {"regions": ["ph"]})
    TikTokAdsDailySpend.objects.create(tenant=tenant, mapping=mapping, date=START, spend="9", currency="PHP")
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None

    scope.config = {"regions": ["PH"], "warehouse_ids": [None]}
    scope.save(update_fields=["config"])
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None

    scope.config = {"store_ids": [True]}
    scope.save(update_fields=["config"])
    _, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)
    assert result[("PHP", START.isoformat())] is None
