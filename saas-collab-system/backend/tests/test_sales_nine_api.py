from datetime import UTC, date, datetime, timedelta

import pytest
from apps.commerce.models import SalesOrder
from apps.masterdata.models import StoreMaster
from apps.permissions.models import UserRole
from apps.sales_management.nine_snapshot_capture import capture_store
from apps.sales_management.snapshot_models import SalesNineSnapshot
from tests.test_sales_realtime_board import _fixture, _grant, _order

URL = '/api/internal/commerce/sales-nine-snapshots/'
DAY = date(2026, 8, 17)


def snapshot(tenant, store, day, amount='100', currency='PHP', zone='Asia/Manila'):
    return SalesNineSnapshot.objects.create(
        tenant=tenant, store=store, business_date=day, timezone_name=zone,
        target_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=1),
        captured_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=1, minutes=1),
        groups=[{'currency': currency, 'sales_amount': amount, 'order_count': 2}],
        integrity_status='unverified', integrity_reason='Source coverage unknown',
    )


@pytest.mark.django_db
def test_nine_snapshot_missing_is_not_zero_and_invalid_queries_rejected():
    *_, client = _fixture('nine-read-missing')
    response = client.get(URL, {'date': DAY.isoformat()})
    assert response.status_code == 200
    data = response.json()['data']
    assert data['rows'][0]['status'] == 'missing'
    assert data['rows'][0]['groups'] == []
    assert data['comparison_allowed'] is False
    for query in [{'date': 'bad'}, {'page_size': '51'}, {'store_id': '-1'}, {'date': '0001-01-01'}, {'other': '1'}]:
        assert client.get(URL, query).status_code == 400
    assert client.get(URL + '?date=2026-08-17&date=2026-08-18').status_code == 400


@pytest.mark.django_db
def test_nine_snapshot_full_week_needed_and_same_currency_only():
    user, tenant, platform, store, run, client = _fixture('nine-read-week')
    snapshot(tenant, store, DAY, '80')
    for index in range(6):
        snapshot(tenant, store, DAY - timedelta(days=7-index), str(100+index))
    def group():
        return client.get(URL, {'date': DAY.isoformat()}).json()['data']['rows'][0]['groups'][0]
    row = group()
    assert row['sales_amount'] == '80'
    assert row['baselines']['previous_day']['sales_amount'] is None
    assert row['baselines']['previous_week_same_day']['sales_amount'] == '100'
    assert row['baselines']['previous_week_average']['sample_count'] == 6
    assert row['baselines']['previous_week_average']['sales_amount'] is None
    snapshot(tenant, store, DAY-timedelta(days=1), '106')
    assert group()['baselines']['previous_week_average']['sales_amount'] == '103'
    # A store's timezone edits cannot silently make historical cutoffs comparable.
    store.timezone = 'Asia/Bangkok'
    store.save(update_fields=['timezone'])
    assert group()['baselines']['previous_week_same_day']['sales_amount'] == '100'
    # An actual historical baseline with a different capture timezone is rejected.
    SalesNineSnapshot.objects.filter(store=store, business_date=DAY-timedelta(days=7)).update(timezone_name='Asia/Bangkok')
    assert group()['baselines']['previous_week_same_day']['sales_amount'] is None


@pytest.mark.django_db
def test_nine_snapshot_uses_live_scope_tenant_and_bounded_pagination():
    user, tenant, platform, store, run, client = _fixture('nine-read-scope')
    extra = StoreMaster.objects.create(tenant=tenant, platform=platform, code='extra', name='Hidden', country_code='TH', currency='THB', timezone='Asia/Bangkok')
    snapshot(tenant, store, DAY)
    snapshot(tenant, extra, DAY, '999999')
    other = _fixture('nine-read-foreign')
    snapshot(other[1], other[3], DAY, '888888')
    first = client.get(URL, {'date': DAY.isoformat(), 'page_size': 1}).json()['data']
    assert len(first['rows']) == 1 and first['has_next'] is True
    UserRole.objects.filter(user=user).delete()
    _grant(user, 'sales_management.view', {'store_ids': [store.pk]})
    data = client.get(URL, {'date': DAY.isoformat()}).json()['data']
    assert [r['store_id'] for r in data['rows']] == [store.pk]
    assert '999999' not in str(data) and '888888' not in str(data)
    assert client.get(URL, {'date': DAY.isoformat(), 'store_id': extra.pk}).json()['data']['rows'] == []


@pytest.mark.django_db
def test_nine_snapshot_endpoint_requires_existing_sales_permission():
    user, tenant, platform, store, run, client = _fixture('nine-read-denied')
    UserRole.objects.filter(user=user).delete()
    assert client.get(URL).status_code == 403


@pytest.mark.django_db
def test_region_scope_cannot_read_store_snapshot_but_store_scope_or_allows_it():
    user, tenant, platform, store, run, client = _fixture('nine-read-region-snapshot')
    sampled_orders_at = datetime(2026, 8, 17, 0, 15, tzinfo=UTC)
    for external_id, region in [('ph-order', 'PH'), ('th-order', 'TH'), ('empty-region-order', '')]:
        order = _order(tenant, platform, store, run, external_id)
        SalesOrder.objects.filter(pk=order.pk).update(
            created_at_utc=sampled_orders_at, region=region
        )

    captured, created = capture_store(store, datetime(2026, 8, 17, 1, 1, tzinfo=UTC))
    assert created is True
    assert captured.groups == [{'currency': 'PHP', 'sales_amount': '300.0000', 'order_count': 3}]

    UserRole.objects.filter(user=user).delete()
    _grant(user, 'sales_management.view', {'regions': ['PH']})
    region_only = client.get(URL, {'date': DAY.isoformat()}).json()['data']
    assert region_only['rows'] == []
    assert '300.0000' not in str(region_only)

    _grant(user, 'sales_management.view', {'store_ids': [store.pk]})
    store_or_region = client.get(URL, {'date': DAY.isoformat()}).json()['data']
    assert [row['store_id'] for row in store_or_region['rows']] == [store.pk]
    assert store_or_region['rows'][0]['groups'][0]['sales_amount'] == '300.0000'
