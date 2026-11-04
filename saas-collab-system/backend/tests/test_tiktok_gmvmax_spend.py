import pytest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from apps.sales_management import tiktok_gmvmax


@pytest.mark.parametrize("missing_rate", [False, True])
@pytest.mark.parametrize("mode", ["normal", "overflow", "conflict", "missing_day"])
def test_gmvmax_spend_accepts_store_id_and_converts_snapshot_currency(monkeypatch, missing_rate, mode):
    user = SimpleNamespace(is_active=True, user_type="internal", tenant_id=7, tenant=object())
    store = SimpleNamespace(pk=31, id=31, currency="PHP", country_code="PH")
    config = SimpleNamespace(platform="tiktok", environment="pilot", regions=[], pk=8)
    mapping = SimpleNamespace(store_id=31, store=store, integration_config=config,
                              advertiser_id="adv-1", currency="USD")

    class StoreQuery:
        def values_list(self, *args, **kwargs):
            return [31]

    class MappingQuery:
        def select_related(self, *args):
            return [mapping]

    monkeypatch.setattr(tiktok_gmvmax, "filter_advertising_stores", lambda user, qs: StoreQuery())
    monkeypatch.setattr(tiktok_gmvmax.StoreMaster.objects, "filter", lambda **kwargs: object())
    monkeypatch.setattr(tiktok_gmvmax.TikTokAdsAdvertiserMapping.objects, "filter", lambda **kwargs: MappingQuery())
    monkeypatch.setattr(tiktok_gmvmax, "permission_scope_configs", lambda *a, **kw: None)
    monkeypatch.setattr(tiktok_gmvmax, "stored_days", lambda *a, **kw: [
        {"advertiser_id": "adv-1", "date": "2026-11-03", "currency": "USD", "cost": "10"},
    ])
    monkeypatch.setattr(tiktok_gmvmax, "tenant_cny_rates", lambda tenant: {
        **({} if missing_rate or mode != "normal" else {"USD": {"rate": Decimal("2")}}), "PHP": {"rate": Decimal("4")},
    })

    if mode == "overflow":
        def overflow(*args, **kwargs):
            raise tiktok_gmvmax.GMVMaxSnapshotOverflow()
        monkeypatch.setattr(tiktok_gmvmax, "stored_days", overflow)
    elif mode == "conflict":
        monkeypatch.setattr(tiktok_gmvmax, "stored_days", lambda *a, **kw: [
            {"advertiser_id": "adv-1", "date": "2026-11-03", "currency": "USD", "cost": cost,
             "platform_store_id": identity, "timezone": "Asia/Manila"}
            for identity, cost in [("old", "10"), ("new", "12")]
        ])
    elif mode == "missing_day":
        monkeypatch.setattr(tiktok_gmvmax, "stored_days", lambda *a, **kw: [])
    spend, failed, available = tiktok_gmvmax.gmvmax_spend(
        user, [{"store_id": 31}], date(2026, 11, 3), date(2026, 11, 3),
    )

    assert available is True
    assert failed == ({31} if missing_rate or mode != "normal" else set())
    assert spend == ({} if missing_rate or mode != "normal" else {(31, "2026-11-03", "PHP"): Decimal("20")})
