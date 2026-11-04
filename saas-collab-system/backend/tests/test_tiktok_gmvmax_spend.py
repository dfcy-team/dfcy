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
    monkeypatch.setattr(tiktok_gmvmax, "preferred_tiktok_days", lambda *a, **kw: [
        {"advertiser_id": "adv-1", "date": "2026-11-03", "currency": "USD", "cost": "10"},
    ])
    monkeypatch.setattr(tiktok_gmvmax, "tenant_cny_rates", lambda tenant: {
        **({} if missing_rate or mode != "normal" else {"USD": {"rate": Decimal("2")}}), "PHP": {"rate": Decimal("4")},
    })

    if mode == "overflow":
        def overflow(*args, **kwargs):
            raise tiktok_gmvmax.GMVMaxSnapshotOverflow()
        monkeypatch.setattr(tiktok_gmvmax, "preferred_tiktok_days", overflow)
    elif mode == "conflict":
        monkeypatch.setattr(tiktok_gmvmax, "preferred_tiktok_days", lambda *a, **kw: [
            {"advertiser_id": "adv-1", "date": "2026-11-03", "currency": "USD", "cost": cost,
             "platform_store_id": identity, "timezone": "Asia/Manila"}
            for identity, cost in [("old", "10"), ("new", "12")]
        ])
    elif mode == "missing_day":
        monkeypatch.setattr(tiktok_gmvmax, "preferred_tiktok_days", lambda *a, **kw: [])
    spend, failed, available = tiktok_gmvmax.gmvmax_spend(
        user, [{"store_id": 31}], date(2026, 11, 3), date(2026, 11, 3),
    )

    assert available is True
    assert failed == ({31} if missing_rate or mode != "normal" else set())
    assert spend == ({} if missing_rate or mode != "normal" else {(31, "2026-11-03", "PHP"): Decimal("20")})

@pytest.mark.django_db
def test_real_stored_snapshot_uses_latest_audit_not_raw_creation(monkeypatch):
    from apps.integrations.models import SharedAdvertisingRawPayload, IntegrationAuditLog
    from apps.integrations.gmv_max_sync import REPORT_PATH, PAGE_SIZE
    from apps.integrations.gmv_max_read import stored_days
    from tests.test_sales_realtime_board import _fixture, _grant
    user, tenant, platform, store, run, client = _fixture('stored-gmv-audit')
    mapping = SimpleNamespace(pk=1, store_id=store.id, store=store, advertiser_id='123')
    raws = []
    for index, cost in enumerate(['10', '12']):
        raws.append(SharedAdvertisingRawPayload.objects.create(
            tenant=tenant, store=store, platform='tiktok', endpoint=REPORT_PATH,
            payload_hash=str(index) * 64, payload={
                'schema': 'gmv-max-day-v1', 'advertiser_id': '123', 'date': '2026-11-03',
                'platform_store_id': '999', 'currency': 'USD', 'timezone': 'Asia/Manila',
                'pages': [{'page_info': {'page': 1, 'page_size': PAGE_SIZE, 'total_page': 1, 'total_number': 1},
                    'list': [{'dimensions': {'campaign_id': '111'},
                              'metrics': {'cost': cost, 'gross_revenue': '100', 'orders': '1'}}]}],
            }))
    # A -> B -> A reuses the old immutable RAW but its audit is newest.
    for raw in [raws[0], raws[1], raws[0]]:
        IntegrationAuditLog.objects.create(tenant=tenant, integration_config=run.sync_job.integration_config,
            actor=user, action='ads_gmv_max_day', result='success', masked_detail={'raw_payload_id': raw.pk})
    result = stored_days(user, [mapping], {}, date(2026, 11, 3), date(2026, 11, 3))
    assert len(result) == 1
    assert result[0]['snapshot_id'] == raws[0].pk
    assert Decimal(result[0]['cost']) == Decimal('10')
