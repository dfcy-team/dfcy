from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from django.http import QueryDict

from apps.integrations.models import ShopeeAdvertisingRecord
from apps.masterdata.models import StoreMaster
from apps.sales_management.sales_operations import _payload
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order


def _ops_data(user, store_ids, *, currency=None, view="stores"):
    params = QueryDict(mutable=True)
    params.update({"date_from": DAY, "date_to": DAY, "view": view})
    if view == "products":
        params["store_id"] = str(store_ids[0])
    request = SimpleNamespace(user=user, query_params=params, delivery_store_ids=store_ids)
    return _payload(request)


def _ad(tenant, store, run, key, report_day, currency, expense):
    ShopeeAdvertisingRecord.objects.create(
        tenant=tenant, store=store, source_run=run, kind="shop_daily", record_key=key,
        report_date=date.fromisoformat(report_day), currency=currency, report_timezone="Asia/Manila",
        dimensions={"store_id": str(store.pk), "platform": "shopee", "country": "PH"},
        data={"expense": expense},
    )


@pytest.mark.django_db
def test_partial_shop_daily_calculates_provisional_roi_and_period_delta():
    user, tenant, platform, store, run, _ = _fixture("ops-partial-roi")
    _grant(user, "analytics.view")
    _order(tenant, platform, store, run, "current", amount="80")
    previous = _order(tenant, platform, store, run, "previous", amount="60")
    previous.created_at_utc = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    previous.save(update_fields=["created_at_utc"])
    _ad(tenant, store, run, "ad-current", DAY, "PHP", "20")
    _ad(tenant, store, run, "ad-partial", DAY, "PHP", "bad")
    _ad(tenant, store, run, "ad-previous", "2026-08-16", "PHP", "30")

    data = _ops_data(user, [store.pk])
    row = data["rows"][0]
    assert row["ad_spend"] == "20"
    assert row["roi"] == "4"
    assert row["roi_delta"] == "2"
    assert row["ad_reason"] == "数据拉取不全，按已入库数据计算（暂估）"


@pytest.mark.django_db
def test_roi_requires_analytics_permission_and_positive_matching_currency_expense():
    user, tenant, platform, store, run, _ = _fixture("ops-roi-scope")
    _order(tenant, platform, store, run, "sales", amount="80")
    _ad(tenant, store, run, "wrong-currency", DAY, "USD", "20")
    no_permission = _ops_data(user, [store.pk])["rows"][0]
    assert no_permission["roi"] is None
    assert no_permission["ad_reason"] == "暂无广告数据查看权限。"

    _grant(user, "analytics.view")
    _ad(tenant, store, run, "zero", DAY, "PHP", "0")
    zero = _ops_data(user, [store.pk])["rows"][0]
    assert zero["ad_spend"] == "0"
    assert zero["roi"] is None
    assert "为 0" in zero["ad_reason"]


@pytest.mark.django_db
def test_product_roi_unknown_and_sales_delivery_store_intersection():
    user, tenant, platform, store, run, _ = _fixture("ops-product-roi")
    _grant(user, "analytics.view")
    _grant(user, "sales_management.skus.view")
    _order(tenant, platform, store, run, "sales", amount="80")
    _ad(tenant, store, run, "allowed-ad", DAY, "PHP", "20")
    other = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="other", name="Other", country_code="PH", currency="PHP",
    )
    _order(tenant, platform, other, run, "other-sales", amount="50")
    _ad(tenant, other, run, "not-delivered", DAY, "PHP", "2")

    stores_data = _ops_data(user, [store.pk])
    assert {row["store_id"] for row in stores_data["rows"]} == {store.pk}
    assert stores_data["currency_groups"][0]["ad_spend"] == "20"
    products_data = _ops_data(user, [store.pk], view="products")
    assert products_data["rows"][0]["roi"] is None
    assert products_data["rows"][0]["ad_spend"] is None
    assert products_data["rows"][0]["ad_reason"] == "商品级广告费未采集，无法计算 ROI。"


@pytest.mark.django_db
def test_ad_query_failure_does_not_hide_sales_and_extreme_amount_is_ignored():
    from unittest.mock import patch
    from django.db import DatabaseError
    user, tenant, platform, store, run, _ = _fixture("ops-roi-failsoft")
    _grant(user, "analytics.view")
    _order(tenant, platform, store, run, "sales", amount="80")
    _ad(tenant, store, run, "extreme", DAY, "PHP", "1e9999")
    row = _ops_data(user, [store.pk])["rows"][0]
    assert row["sales_amount"] == "80" and row["roi"] is None
    with patch('apps.sales_management.observed_roi.advertising_queryset', side_effect=DatabaseError('temporary')):
        row = _ops_data(user, [store.pk])["rows"][0]
    assert row["sales_amount"] == "80" and row["roi"] is None
    assert '暂不可用' in row['ad_reason']

@pytest.mark.django_db
def test_currency_roi_matches_only_stores_with_observed_ad_expense():
    user, tenant, platform, store, run, _ = _fixture('ops-roi-subset')
    _grant(user, 'analytics.view')
    _order(tenant, platform, store, run, 'observed', amount='100')
    _ad(tenant, store, run, 'ad-observed', DAY, 'PHP', '20')
    missing = StoreMaster.objects.create(tenant=tenant, platform=platform, code='no-ad', name='No ad', country_code='PH', currency='PHP', timezone='Asia/Manila')
    _order(tenant, platform, missing, run, 'missing-ad', amount='900')
    group = _ops_data(user, [store.pk, missing.pk])['currency_groups'][0]
    assert group['sales_amount'] == '1000'
    assert group['ad_spend'] == '20'
    assert group['roi'] == '5'
    assert '已有广告费的店铺GMV' in group['ad_reason']
