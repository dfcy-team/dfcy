from datetime import date
from decimal import Decimal
from io import BytesIO
import json

import pytest

from apps.masterdata.monthly_exchange_rates import (
    ExchangeRateEvidenceError, fetch_daily_rates, store_daily_rates, monthly_average_quotes,
)
from apps.masterdata.models import DailyExchangeRateSnapshot
from tests.test_sales_management import create_scope, user_for, grant


def response(day, rates):
    return BytesIO(json.dumps({'date': day.isoformat(), 'cny': rates}).encode())


def test_historical_fetch_rejects_wrong_date_and_uses_same_day_fallback():
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        return response(date(2024, 2, 1) if len(calls) == 1 else date(2024, 2, 2), {'usd': .2, 'php': 10})
    result = fetch_daily_rates(date(2024, 2, 2), opener=opener)
    assert result['rates'] == {'CNY': '1', 'USD': '0.2', 'PHP': '10'}
    assert '@2024-02-02/' in calls[0]
    assert '2024-02-02.currency-api.pages.dev' in calls[1]


@pytest.mark.parametrize('bad', [0, -1, 'NaN', 'Infinity'])
def test_invalid_daily_rate_is_not_saved_as_zero(bad):
    with pytest.raises(ExchangeRateEvidenceError):
        fetch_daily_rates(date(2024, 2, 1), opener=lambda *a, **k: response(date(2024, 2, 1), {'usd': bad}))


@pytest.mark.django_db
def test_leap_month_average_uses_daily_cross_rates_and_keeps_evidence():
    tenant, _, _, _ = create_scope('monthly-fx')
    for day in range(1, 30):
        rate = '10' if day < 29 else '20'
        usd = '.2' if day < 29 else '.5'
        store_daily_rates(tenant, date(2024, 2, day), {'CNY': '1', 'USD': usd, 'PHP': rate}, 'https://example.test/daily')
    pairs = [('PH', 'CNY', 'PHP'), ('PH', 'USD', 'PHP')]
    quotes = monthly_average_quotes(tenant, ['2024-02'], pairs)
    cny, usd = [quotes['2024-02|PH|'+base+'|PHP'] for base in ['CNY', 'USD']]
    assert Decimal(cny['rate']) == (Decimal(300) / 29).quantize(Decimal('.0000000001'))
    assert Decimal(usd['rate']) == (Decimal(1440) / 29).quantize(Decimal('.0000000001'))
    assert cny['days'] == cny['expected_days'] == 29
    assert len(cny['daily_ids']) == 29 and len(cny['source_hash']) == 64
    assert cny['basis'] == 'monthly_daily_average'
    assert len(cny['sources']) == 1


@pytest.mark.django_db
def test_missing_day_currency_other_tenant_or_incomplete_month_never_falls_back():
    tenant, _, _, _ = create_scope('fx-gap')
    other, _, _, _ = create_scope('fx-other')
    for day in range(1, 30):
        owner = other if day == 29 else tenant
        store_daily_rates(owner, date(2024, 2, day), {'CNY': '1', 'PHP': '10'}, 'https://example.test/daily')
    pairs = [('PH', 'CNY', 'PHP'), ('PH', 'USD', 'PHP')]
    assert monthly_average_quotes(tenant, ['2024-02'], pairs) == {}
    store_daily_rates(tenant, date(2024, 2, 29), {'CNY': '1', 'PHP': '10'}, 'https://example.test/daily')
    quotes = monthly_average_quotes(tenant, ['2024-02'], pairs)
    assert set(quotes) == {'2024-02|PH|CNY|PHP'}
    assert monthly_average_quotes(tenant, ['2024-02'], pairs, as_of=date(2024, 2, 29)) == {}


@pytest.mark.django_db
def test_daily_import_is_idempotent_and_conflict_or_tampering_is_rejected():
    tenant, _, _, _ = create_scope('fx-immutable')
    args = (tenant, date(2024, 2, 1), {'CNY': '1', 'PHP': '10'}, 'https://example.test/daily')
    first = store_daily_rates(*args)
    assert store_daily_rates(*args).pk == first.pk
    with pytest.raises(ExchangeRateEvidenceError):
        store_daily_rates(tenant, date(2024, 2, 1), {'CNY': '1', 'PHP': '20'}, 'https://example.test/daily')
    assert DailyExchangeRateSnapshot.objects.filter(tenant=tenant).count() == 1
    DailyExchangeRateSnapshot.objects.filter(pk=first.pk).update(rates={'CNY': '1', 'PHP': '20'})
    with pytest.raises(ExchangeRateEvidenceError):
        monthly_average_quotes(tenant, ['2024-02'], [('PH', 'CNY', 'PHP')])


@pytest.mark.django_db
def test_finance_reads_only_saas_monthly_average_and_retirement_is_tenant_scoped():
    from apps.finance.summary_database import collect
    from apps.finance.summary_models import FinanceSummaryInput
    from apps.finance.summary_exchange_rates import retire_html2_monthly_rates
    from apps.finance.summary_service import READ_PERMISSIONS, source_checkpoint
    from apps.finance.models import FinanceAuditLog
    tenant, _, store, _ = create_scope('fx-finance')
    other, _, _, _ = create_scope('fx-finance-other')
    store.country_code = 'PH'; store.currency = 'PHP'; store.save()
    user = user_for(tenant, 'fx-finance')
    other_user = user_for(other, 'fx-finance-other')
    payload = {'basis': 'monthly', 'quote': {'rate': '99', 'basis': 'warehouse_monthly', 'source': '已确认月度业务汇率迁入SaaS'}}
    for owner, actor in [(tenant,user),(other,other_user)]:
        FinanceSummaryInput.objects.create(tenant=owner,kind='exchange_rate',source_key='2024-02|PH|CNY|PHP',period='2024-02',
            payload=payload,source_hash='a'*64,created_by=actor)
    scope = {'stores':[store.pk], 'from':'2024-02-01','to':'2024-02-29'}
    assert collect(user, scope)['rates']['monthly'] == {}
    before = source_checkpoint([store.pk])
    for day in range(1,30):
        store_daily_rates(tenant,date(2024,2,day),{'CNY':'1','PHP':'10'},'https://example.test/daily')
    quote = collect(user,scope)['rates']['monthly']['2024-02|PH|CNY|PHP']
    assert quote['rate'] == '10.0000000000' and quote['basis'] == 'monthly_daily_average'
    assert source_checkpoint([store.pk]) != before
    for code in (*READ_PERMISSIONS,'finance.import'):grant(user,code)
    assert retire_html2_monthly_rates(user) == 1
    assert retire_html2_monthly_rates(user) == 0
    assert FinanceSummaryInput.objects.filter(tenant=other,kind='exchange_rate').count() == 1
    audit = FinanceAuditLog.objects.get(tenant=tenant,action='summary_legacy_fx_retired')
    assert audit.masked_detail['archived_rates'][0]['payload'] == payload
