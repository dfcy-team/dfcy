from types import SimpleNamespace

import pytest
from django.http import QueryDict
from rest_framework.exceptions import ValidationError

from apps.finance.summary_views import table_input


def parse(query):
    return table_input(SimpleNamespace(query_params=QueryDict(query)))


@pytest.mark.parametrize('query', [
    'filter_period_type=day',
    'filter_period_type=week&filter_period=2026-08-31',
    'filter_month=2026-09&filter_period_type=week&filter_period=2026-09-01',
    'filter_month=2026-09&filter_period_type=half_month&filter_period=2026-09-30',
    'filter_month=2026-09&filter_period_type=half_month&filter_period=2026-02-30',
    'filter_month=2026-09&filter_period_type=month&filter_period=undated',
])
def test_period_invalid_values_fail_closed(query):
    with pytest.raises(ValidationError):
        parse(query)


@pytest.mark.parametrize('period_type,period', [('week', '2026-08-31'), ('half_month', '2026-09-16'), ('week', 'undated')])
def test_period_scope_is_preserved(period_type, period):
    data = parse(f'filter_month=2026-09&filter_period_type={period_type}&filter_period={period}')
    assert data['filters'] == {'month': '2026-09', 'period_type': period_type, 'period': period}


def test_monthly_old_payload_unchanged():
    assert parse('filter_month=2026-09')['filters'] == {'month': '2026-09'}
