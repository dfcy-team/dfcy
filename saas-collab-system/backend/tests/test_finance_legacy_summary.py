from decimal import Decimal

import pytest
from apps.finance.models import BankReceiptImport, PlatformStatement, ReconciliationException, ReconciliationMatch, WithdrawalRecord
from apps.tenants.models import Tenant
from tests.test_phase2_finance_reconciliation import authenticated_client, create_user, grant_finance_access


@pytest.mark.django_db
def test_legacy_summary_does_not_repeat_statement_or_copy_receipts_between_periods():
    tenant=Tenant.objects.create(name='Summary',code='legacy-finance-summary')
    user=create_user(tenant,'legacy-summary');grant_finance_access(user)
    first=PlatformStatement.objects.create(tenant=tenant,platform='shopee',statement_no='JAN',period_start='2026-01-01',period_end='2026-01-31',currency='USD',gross_amount='200',fee_amount='20',net_amount='180')
    second=PlatformStatement.objects.create(tenant=tenant,platform='shopee',statement_no='FEB',period_start='2026-02-01',period_end='2026-02-28',currency='USD',gross_amount='100',fee_amount='10',net_amount='90')
    matches=[]
    for i,statement in enumerate((first,first,second)):
        withdrawal=WithdrawalRecord.objects.create(tenant=tenant,platform='shopee',withdrawal_no=f'W-{i}',currency='USD',requested_amount='100',expected_amount='90',requested_at='2026-01-10T00:00:00Z',completed_at='2026-01-10T00:00:00Z',status='completed')
        receipt=BankReceiptImport.objects.create(tenant=tenant,reference_no=f'R-{i}',import_batch_no='B',masked_account='****1234',currency='USD',receipt_amount='90',receipt_date='2026-01-10')
        matches.append(ReconciliationMatch.objects.create(tenant=tenant,statement=statement,withdrawal=withdrawal,bank_receipt=receipt,matched_amount='90',difference_amount='0',status='confirmed'))
    for match in matches[:2]:
        ReconciliationException.objects.create(tenant=tenant,reconciliation_match=match,exception_type='amount_difference',difference_amount='1')
    response=authenticated_client(user).get('/api/finance/analytics/overview/')
    assert response.status_code==200
    rows={str(r['period_start']):r for r in response.data['data']['results']}
    assert Decimal(str(rows['2026-01-01']['statement_amount']))==Decimal('200')
    assert Decimal(str(rows['2026-01-01']['receipt_amount']))==Decimal('180')
    assert rows['2026-01-01']['exception_count']==2
    assert Decimal(str(rows['2026-02-01']['receipt_amount']))==Decimal('90')
    assert rows['2026-02-01']['exception_count']==0
