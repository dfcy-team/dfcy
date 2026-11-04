from datetime import date
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations import gmv_max_read
from apps.integrations.gmv_max_overview import overview, shop_overview
from apps.integrations.gmv_max_sync import summarize


def empty_page(**changes):
    return {'page_info': {'page': 1, 'page_size': 100, 'total_page': 1,
                         'total_number': 0, **changes}, 'list': []}


@pytest.mark.parametrize('total_page', [0, 1])
def test_verified_empty_is_no_data_not_fabricated_zero(total_page):
    result = summarize([empty_page(total_page=total_page)])
    assert result == {'campaign_count': 0, 'cost': None, 'gross_revenue': None,
                      'orders': None, 'collection_status': 'no_data'}


@pytest.mark.parametrize('pages', [[], [{}], [empty_page(total_number=1)],
    [empty_page(page=2)], [empty_page(total_page=2)], [empty_page(), empty_page()]])
def test_malformed_or_incomplete_report_is_not_no_data(pages):
    with pytest.raises(ValidationError):
        summarize(pages)


def sample(**changes):
    return {'store_code': 'S', 'advertiser_id': 'a', 'advertiser_name': '',
            'platform_store_id': 'p', 'currency': 'USD', 'timezone': 'UTC',
            'date': '2026-11-01', 'cost': '2', 'gross_revenue': '6', 'orders': 1,
            **changes}


def test_empty_days_count_as_covered_without_changing_amounts():
    rows = [sample(), sample(date='2026-11-02', **summarize([empty_page()]))]
    args = (date(2026, 11, 1), date(2026, 11, 2))
    result = overview(rows, *args)[0]
    assert result['complete'] and result['no_data_days'] == 1
    assert result['cost'] == '2' and result['roi'] == '3.00'
    no_data = overview(rows[1:], date(2026, 11, 2), date(2026, 11, 2))[0]
    assert no_data['complete'] and no_data['cost'] is None
    sub = {'store_code': 'S', 'advertiser_id': 'a', 'currency': 'USD',
           'mapping_timezone': 'UTC', 'historical_binding_confirmed': True}
    result = shop_overview(rows[1:], [sub], date(2026, 11, 2), date(2026, 11, 2))[0]
    assert result['complete'] and result['cost'] is None


def test_failed_missing_and_empty_are_distinct_and_scoped(monkeypatch):
    mapping = SimpleNamespace(pk=1, store_id=3, advertiser_id='a', currency='USD',
                              timezone='UTC', integration_config_id=4,
                              store=SimpleNamespace(code='S'))
    def audit(**changes):
        return SimpleNamespace(integration_config_id=4, masked_detail={
            'mapping_id': 1, 'store_id': 3, 'advertiser_id': 'a', 'currency': 'USD',
            'timezone': 'UTC', 'date': '2026-11-02', 'error_code': 'provider_read_rejected',
            **changes})
    attempts = [audit(advertiser_id='other', date='2026-11-03'), audit()]
    class Query(list):
        def order_by(self, *args):
            return self
    class Manager:
        def filter(self, **kwargs):
            assert kwargs['tenant_id'] == 9
            assert kwargs['masked_detail__mapping_id__in'] == [1]
            return Query(attempts)
    monkeypatch.setattr(gmv_max_read.IntegrationAuditLog, 'objects', Manager())
    rows = [sample(**summarize([empty_page()]))]
    result = gmv_max_read.collection_days(SimpleNamespace(tenant_id=9), [mapping], {}, rows,
                                          date(2026, 11, 1), date(2026, 11, 3))
    assert [r['status'] for r in result] == ['no_data', 'failed', 'not_collected']
    result = gmv_max_read.collection_days(SimpleNamespace(tenant_id=9), [mapping], {},
        rows + [sample(date='2026-11-02')], date(2026, 11, 1), date(2026, 11, 2))
    assert result[-1]['status'] == 'success' and result[-1]['error_code'] is None


@pytest.mark.parametrize('commit', [False, True])
def test_scheduler_persists_only_sanitized_committed_failure_attempts(monkeypatch, commit):
    from unittest.mock import Mock
    from django.core.management.base import CommandError
    from django.db import OperationalError
    from apps.integrations.management.commands import sync_tiktok_gmv_max_recent as command
    actor = SimpleNamespace(pk=2, tenant_id=9, is_active=True)
    mapping = SimpleNamespace(pk=1, store_id=3, advertiser_id='a', currency='USD',
                              timezone='UTC', integration_config_id=4)
    class Query(list):
        def select_related(self, *args): return self
        def order_by(self, *args): return self
        def iterator(self): return iter(self)
    monkeypatch.setattr(command, 'get_user_model', lambda: SimpleNamespace(
        objects=SimpleNamespace(get=lambda **kwargs: actor)))
    monkeypatch.setattr(command.TikTokAdsAdvertiserMapping, 'objects', SimpleNamespace(
        filter=lambda **kwargs: Query([mapping])))
    monkeypatch.setattr(command, 'user_has_integration_permission', lambda *args: True)
    monkeypatch.setattr(command, 'mapping_allowed', lambda *args: True)
    monkeypatch.setattr(command, 'validate_mapping', lambda *args: None)
    monkeypatch.setattr(command, 'shop_authorization', lambda *args: None)
    monkeypatch.setattr(command, 'probe_relationship', lambda **kwargs: {'relationship_status': 'current_verified'})
    monkeypatch.setattr(command, 'complete_days', lambda *args: [date(2026, 11, 1)])
    collect = Mock(side_effect=OperationalError('secret must not be stored'))
    monkeypatch.setattr(command, 'run_day', collect)
    create = Mock()
    monkeypatch.setattr(command.IntegrationAuditLog, 'objects', SimpleNamespace(create=create))
    runner = command.Command()
    runner.stdout = Mock()
    if commit:
        with pytest.raises(CommandError):
            runner.handle(tenant_id=9, actor_id=2, commit=True)
        detail = create.call_args.kwargs['masked_detail']
        assert detail['error_code'] == 'database_operation_failed'
        assert detail['date'] == '2026-11-01' and detail['mapping_id'] == 1
        assert 'secret' not in str(create.call_args) + str(runner.stdout.write.call_args_list)
    else:
        runner.handle(tenant_id=9, actor_id=2, commit=False)
        create.assert_not_called()
        collect.assert_not_called()
