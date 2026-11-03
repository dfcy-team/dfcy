from decimal import Decimal

import pytest
from django.db.models import Sum
from rest_framework.exceptions import ValidationError

from apps.finance.models import FinanceAuditLog
from apps.finance.warehouse_bill_parser import BillReader, parse_bill
from apps.finance.warehouse_bill_settlement import POLICY, SOURCE_TYPE, invoice_plan, reconcile
from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from apps.finance.warehouse_fee_services import create_fee, operate, representation
from tests.test_warehouse_fees import context, payload, local_order
from tests.test_warehouse_bill_uploads import workbook


pytestmark = pytest.mark.django_db


def bill_job(context, *, order='100', other='20', detail='100', currency='CNY'):
    user = context[1]
    return WarehouseBillUpload.objects.create(tenant=user.tenant, uploaded_by=user,
        file_name='WAREHOUSE-2026-09.xlsx', file_hash='b' * 64, status='ready', summary={
            'country': 'PH', 'bill_month': '2026-09', 'currency': currency, 'order_detail_sum': detail,
            'settlement': {'policy': POLICY, 'valid': bool(currency), 'bill_number': 'WAREHOUSE-2026-09',
                'country': 'PH', 'bill_month': '2026-09', 'currency': currency, 'lines': [],
                'order_total': order, 'other_total': other, 'total': str(Decimal(order) + Decimal(other))}})


def registered_total(context):
    return WarehouseFee.objects.filter(tenant=context[1].tenant, status='registered').aggregate(total=Sum('amount'))['total']


def test_invoice_not_supporting_sheets_controls_total(tmp_path):
    path = tmp_path / 'bill.xlsx'
    path.write_bytes(workbook({'业务结算单': [
        ['菲律宾2026年9月'], [None]*6 + [100, '代发费'], [None]*6 + [20, '其他应收费用'],
        ['合计'] + [None]*5 + [118]], '其他明细': [['仓租', 99999]]}))
    reader = BillReader(path)
    try:
        plan = invoice_plan(reader, {'bill_number': 'BILL', 'country': 'PH', 'bill_month': '2026-09', 'currency': 'CNY'})
    finally:
        reader.close()
    assert plan['total'] == '118.000000'
    assert plan['order_total'] == '100.000000' and plan['other_total'] == '18.000000'
    assert plan['line_difference'] == '-2.000000'


def test_pending_warehouse_and_signed_difference_are_audited_and_idempotent(context):
    job = bill_job(context, order='100', detail='101')
    reconcile(context[1], job.pk, activate=True)
    fees = WarehouseFee.objects.filter(source__type=SOURCE_TYPE)
    assert fees.count() == 3 and registered_total(context) == Decimal('120')
    assert fees.get(source__component='order_difference').amount == Decimal('-1')
    assert all(fee.warehouse_id is None for fee in fees)
    assert representation(fees.first())['warehouse_code'] == '待分配'
    before = FinanceAuditLog.objects.count()
    reconcile(context[1], job.pk)
    assert fees.count() == 3 and FinanceAuditLog.objects.count() == before


def test_register_correct_and_void_automatically_rebalance_same_invoice(context):
    job = bill_job(context)
    reconcile(context[1], job.pk, activate=True)
    fee, _ = create_fee(context[1], payload(context, amount='4'))
    with pytest.raises(ValidationError, match='待核对'):
        operate(context[1], fee.pk, 'register', fee.version)
    assert registered_total(context) == Decimal('120')
    assert WarehouseFee.objects.get(source__component='order_pending').amount == Decimal('100')
    local_order(context)
    fee = operate(context[1], fee.pk, 'register', fee.version)
    pending = WarehouseFee.objects.get(source__component='order_pending')
    assert pending.amount == Decimal('96') and registered_total(context) == Decimal('120')
    fee = operate(context[1], fee.pk, 'correct', fee.version, changes={'amount': '6'}, reason='账单分摊核对')
    pending.refresh_from_db()
    assert pending.amount == Decimal('94') and registered_total(context) == Decimal('120')
    operate(context[1], fee.pk, 'void', fee.version, reason='撤回明细分摊')
    pending.refresh_from_db()
    assert pending.amount == Decimal('100') and registered_total(context) == Decimal('120')


def test_managed_balance_cannot_be_changed_as_an_independent_expense(context):
    job = bill_job(context)
    reconcile(context[1], job.pk, activate=True)
    fee = WarehouseFee.objects.get(source__component='order_pending')
    with pytest.raises(ValidationError):
        operate(context[1], fee.pk, 'correct', fee.version, changes={'amount': '999'}, reason='试改')
    assert registered_total(context) == Decimal('120')


def test_unknown_currency_and_foreign_tenant_cannot_activate(context):
    job = bill_job(context, currency='')
    with pytest.raises(ValidationError):
        reconcile(context[1], job.pk, activate=True)
    assert not WarehouseFee.objects.exists()


@pytest.mark.parametrize('matching', ['missing_order', 'manual_confirmed', 'matched'])
def test_original_bill_unmatched_order_cannot_bypass_local_order_check(context, matching):
    source = {'type': 'warehouse_original_xlsx', 'original_order_id': 'NOT-LOCAL-YET',
              'matching': {'status': matching}, 'sha256': 'b' * 64}
    with pytest.raises(ValidationError, match='待核对'):
        create_fee(context[1], payload(context), source=source)
    assert not WarehouseFee.objects.exists()


def test_public_input_cannot_forge_negative_or_unallocated_adjustments(context):
    client = context[0]
    response = client.post('/api/finance/warehouse-fees/', payload(context, kind='other',
        store_id=None, external_order_id='', warehouse_id=None, amount='-1'), format='json')
    assert response.status_code == 400 and not WarehouseFee.objects.exists()


def test_pending_warehouse_fees_are_included_in_finance_ledger(context):
    from apps.finance.ledger import collect_records
    from tests.test_sales_management import grant
    grant(context[1], 'finance.view')
    job = bill_job(context, order='100', detail='101')
    reconcile(context[1], job.pk, activate=True)
    records, _ = collect_records(context[1], {})
    fees = [row for row in records if row['source_id'].startswith('warehouse:')]
    assert sum(row['amount'] for row in fees) == Decimal('-120')
    assert all(row['warehouse_id'] is None for row in fees)


def test_country_fee_rollup_does_not_require_sales_order_allocation(context):
    from unittest.mock import patch
    from apps.finance.ledger import report
    from tests.test_sales_management import grant
    grant(context[1], 'finance.view')
    job = bill_job(context)
    reconcile(context[1], job.pk, activate=True)
    with patch('apps.finance.ledger.sales_weights', side_effect=AssertionError('Country totals do not allocate orders')), \
            patch('apps.finance.ledger.platform_records', side_effect=AssertionError('Unrelated platform history must not block warehouse totals')):
        result = report(context[1], {'view': 'country', 'kind': 'warehouse_other', 'page': 1, 'page_size': 20})
    assert result['totals'][0]['balance'] == Decimal('-120')


def test_settlement_api_requires_register_and_edit_permissions(context):
    from tests.test_sales_management import grant, user_for, client_for
    job = bill_job(context)
    response = context[0].post(f'/api/finance/warehouse-fees/original-bills/{job.pk}/',
        {'operation': 'settle', 'version': job.version}, format='json')
    assert response.status_code == 200, response.data
    assert registered_total(context) == Decimal('120')
    limited = user_for(context[1].tenant, 'only-original-import')
    grant(limited, 'finance.warehouse_fees.import')
    other = WarehouseBillUpload.objects.create(tenant=limited.tenant, uploaded_by=limited,
        file_hash='c'*64, file_name='OTHER.xlsx', status='ready', summary=job.summary)
    response = client_for(limited).post(f'/api/finance/warehouse-fees/original-bills/{other.pk}/',
        {'operation': 'settle', 'version': other.version}, format='json')
    assert response.status_code == 403


def test_duplicate_rows_are_kept_separately_and_unmatched_orders_are_pending(context, tmp_path):
    from tests.test_warehouse_bill_uploads import ph_bill
    from apps.finance.warehouse_bill_uploads import normalize_rows
    path = tmp_path / 'duplicate.xlsx'
    path.write_bytes(ph_bill(context[2].code, context[3].code, duplicate=True, total=8, order='NOT-LOCAL-YET'))
    facts, summary = parse_bill(path, '2026年9月菲律宾处理费.xlsx')
    rows = list(normalize_rows(context[1], facts, {}, path.name, 'b'*64, summary['settlement']))[:-1]
    orders = [row for row in rows if row.data['kind'] == 'order']
    assert len(orders) == 2 and all(row.status == 'error' for row in orders)
    assert len({row.data['reference'] for row in orders}) == 2
    assert all(row.source['possible_duplicate'] and row.source['order_unlinked'] for row in orders)


def test_cross_currency_registration_rolls_back_without_double_counting(context):
    local_order(context)
    job = bill_job(context)
    reconcile(context[1], job.pk, activate=True)
    fee, _ = create_fee(context[1], payload(context, currency='PHP'))
    with pytest.raises(ValidationError):
        operate(context[1], fee.pk, 'register', fee.version)
    fee.refresh_from_db()
    assert fee.status == 'draft' and registered_total(context) == Decimal('120')


def test_renaming_same_source_cannot_create_a_second_bill(context):
    job = bill_job(context)
    reconcile(context[1], job.pk, activate=True)
    with pytest.raises(ValidationError, match='改名'):
        create_fee(context[1], payload(context, bill_number='RENAMED'),
                   source={'type': 'warehouse_original_xlsx', 'sha256': job.file_hash})
    other = WarehouseBillUpload.objects.create(tenant=context[1].tenant, uploaded_by=context[1],
        file_hash='d'*64, file_name='RENAMED.xlsx', summary=job.summary)
    other.summary['settlement'] = {**job.summary['settlement'], 'bill_number': 'RENAMED'}
    other.file_hash = job.file_hash
    # Another user's upload has the same content but a renamed business bill.
    from tests.test_sales_management import user_for
    other.uploaded_by = user_for(context[1].tenant, 'renamed-source-owner')
    other.save()
    with pytest.raises(ValidationError, match='改名'):
        reconcile(context[1], other.pk, activate=True)
    assert registered_total(context) == Decimal('120')
