from unittest.mock import patch
from types import SimpleNamespace
import pytest
from apps.integrations.feishu_reports import build_report
from tests.test_sales_realtime_board import _fixture, _order
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from tests.test_sales_management import create_order, create_scope, grant, user_for

@pytest.mark.django_db
def test_no_relationship_suppresses_even_with_global_permission():
    user, tenant, platform, store, run, client = _fixture('rel-none')
    result = build_report({'config': {'report_type': 'sales_daily'}}, user)
    assert result['suppress_reason'] == 'NO_RELATED_STORES'

@pytest.mark.django_db
def test_owner_leader_union_is_tenant_scoped_and_injected_before_aggregation():
    user, tenant, platform, store, run, client = _fixture('rel-both')
    StoreMaster.objects.filter(pk=store.pk).update(operator=user, leader=user)
    _order(tenant, platform, store, run, 'mine')
    with patch('apps.integrations.feishu_sales_operations.build_operations_report', return_value={}) as build:
        build_report({'config': {'report_type': 'sales_daily'}}, user)
    assert build.call_args.kwargs['store_ids'] == [store.pk]
    with patch('apps.integrations.feishu_anomaly_reports.build_anomaly_report', return_value={}) as build:
        build_report({'config': {'report_type': 'sales_anomalies'}}, user)
    assert 'store_ids' not in build.call_args.args[2]
    assert build.call_args.kwargs['delivery_store_ids'] == [store.pk]

@pytest.mark.django_db
def test_sales_payload_relationship_never_grants_unassigned_store_data():
    from apps.sales_management.sales_operations import _payload
    from django.http import QueryDict
    user, tenant, platform, store, run, client = _fixture('rel-intersect')
    _order(tenant, platform, store, run, 'visible-by-permission')
    query = QueryDict('date_from=2026-08-17&date_to=2026-08-17')
    data = _payload(SimpleNamespace(user=user, query_params=query, delivery_store_ids=[]))
    assert data['rows'] == [] and data['currency_groups'] == []

@pytest.mark.django_db
def test_shared_inventory_does_not_require_store_relationship():
    user, tenant, platform, store, run, client = _fixture('rel-inventory')
    result = {'status': 'available', 'rows': [], 'dataset': 'inventory'}
    with patch('apps.integrations.feishu_reports._query', return_value={}) as query, patch('apps.integrations.feishu_reports._section', return_value=result), patch('apps.integrations.feishu_reports._summary', return_value='shared inventory'):
        report = build_report({'config': {'report_type': 'inventory'}}, user)
        assert query.call_count == 1
        assert not report.get('suppress_delivery', False)
        assert 'store_ids' not in query.call_args.args[2]
        query.reset_mock()
        report = build_report({'config': {'report_type': 'comprehensive'}}, user)
        assert {call.args[1] for call in query.call_args_list} == {'inventory', 'inventory_value'}


@pytest.mark.django_db
def test_more_than_100_related_stores_are_kept_but_intersected_with_live_permission():
    tenant, platform, allowed_store, _ = create_scope('rel-large-scope')
    user = user_for(tenant, 'rel-large-recipient')
    grant(user, 'reports.view')
    grant(user, 'sales_management.view', DataScope.ScopeType.CUSTOM, {'store_ids': [allowed_store.pk]})
    related = [allowed_store]
    for offset in range(101):
        related.append(StoreMaster.objects.create(
            pk=10000 + offset, tenant=tenant, platform=platform, code=f'rel-large-{offset}',
            name=f'Related {offset}', country_code='PH', currency='PHP', timezone='Asia/Manila', operator=user,
        ))
    StoreMaster.objects.filter(pk=allowed_store.pk).update(operator=user)
    create_order(tenant, allowed_store, 'rel-large-allowed')
    create_order(tenant, related[-1], 'rel-large-denied')

    report = build_report(
        {'config': {'report_type': 'sales', 'filters': {'date_from': '2026-08-17', 'date_to': '2026-08-17'}}},
        user,
    )

    section = report['sections'][0]
    assert sum(row['order_count'] for row in section['rows']) == 1
    assert sum(row['gross_sales'] for row in section['rows']) == 100
    assert len(related) == 102 and len(','.join(str(store.pk) for store in related)) > 300
