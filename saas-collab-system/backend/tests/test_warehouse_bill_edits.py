from unittest.mock import patch

import pytest
from apps.commerce.models import SalesOrder

from apps.finance.models import FinanceAuditLog
from apps.finance.warehouse_bill_uploads import process_job, source_path
from apps.finance.warehouse_fee_models import WarehouseFee
from tests.test_sales_management import create_scope, user_for, client_for, grant
from tests.test_warehouse_bill_uploads import URL, context, ph_bill, uploaded

pytestmark = pytest.mark.django_db


def parsed(context, raw=None):
    job = uploaded(context, raw)
    process_job(str(job.pk), job.version, 'parse')
    job.refresh_from_db()
    assert job.status == 'ready', job.error
    return job


def edit(context, job, fields=None, *, rows=None, operation='edit', **extra):
    return context[0].post(URL + str(job.pk) + '/', {
        'operation': operation, 'version': job.version,
        'rows': rows or [{'number': 1, 'changes': fields or {}}],
        'reason': '核对原账单后修正', **extra,
    }, format='json')


def test_edit_keeps_source_and_original_totals_and_never_imports(context):
    job = parsed(context)
    raw = source_path(job).read_bytes()
    response = edit(context, job, {'amount': '4.125678', 'note': '补充说明'})
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    row = job.rows.get(number=1)
    assert row.data['amount'] == '4.125678' and row.data['note'] == '补充说明'
    assert row.source['original_data']['amount'] == '4.000000'
    assert row.source['raw_amount'] == '4' and source_path(job).read_bytes() == raw
    assert job.summary['totals'] == [{'currency': 'CNY', 'amount': '12.000000'}]
    assert job.summary['corrected_totals'] == [{'currency': 'CNY', 'amount': '12.125678'}]
    assert row.status == 'valid'
    assert job.summary['corrected_order_difference'] == '0.125678'
    assert not WarehouseFee.objects.exists()
    assert FinanceAuditLog.objects.filter(object_type='warehouse_bill_row', actor=context[1], action='edit').count() == 1


def test_explicit_row_mapping_clears_unresolved_status(context):
    job = parsed(context, ph_bill())
    _, _, store, warehouse = context
    response = edit(context, job, rows=[
        {'number': 1, 'changes': {'store_id': store.pk, 'warehouse_id': warehouse.pk}},
        {'number': 2, 'changes': {'warehouse_id': warehouse.pk}},
    ])
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.rows.filter(status='valid').count() == 2
    assert job.summary['unresolved'] == {'stores': [], 'warehouses': []}
    assert not WarehouseFee.objects.exists()


def test_reparse_preserves_corrections_and_restore_revalidates(context):
    job = parsed(context)
    assert edit(context, job, {'external_order_id': '000012345678901234567890', 'note': '已核实'}).status_code == 200
    job.refresh_from_db()
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = context[0].post(URL + str(job.pk) + '/', {
            'operation': 'parse', 'version': job.version, 'options': {'stores': {}, 'warehouses': {}},
        }, format='json')
    assert response.status_code == 202
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    row = job.rows.get(number=1)
    assert row.data['external_order_id'] == '000012345678901234567890'
    assert row.source['original_data']['external_order_id'] == 'ORDER001'
    assert edit(context, job, operation='restore').status_code == 200
    job.refresh_from_db(); row.refresh_from_db()
    assert row.data['external_order_id'] == 'ORDER001' and row.status == 'valid'
    assert not row.source.get('correction')
    assert FinanceAuditLog.objects.filter(object_type='warehouse_bill_row', action='restore').count() == 1


@pytest.mark.parametrize('changes', [
    {'amount': '-1'}, {'amount': '1.0000001'}, {'amount': 'NaN'},
    {'currency': 'INVALID'}, {'external_order_id': 123}, {'external_order_id': '1.23E+18'},
    {'occurred_on': '2026/09/01'}, {'occurred_on': '2026-9-1'}, {'kind': 'other'}, {'country': 'TH'}, {'status': 'valid'},
])
def test_invalid_and_readonly_changes_are_rejected_atomically(context, changes):
    job = parsed(context)
    before = job.rows.get(number=1).data
    assert edit(context, job, changes).status_code == 400
    job.refresh_from_db()
    assert job.version == 1 and job.rows.get(number=1).data == before
    assert not FinanceAuditLog.objects.filter(object_type='warehouse_bill_row').exists()


def test_foreign_or_cross_country_targets_are_rejected(context):
    job = parsed(context)
    _, _, foreign_store, foreign_wh = create_scope('foreign-row-edit')
    for changes in [{'store_id': foreign_store.pk}, {'warehouse_id': foreign_wh.pk}]:
        assert edit(context, job, changes).status_code == 400
    warehouse = context[3]; warehouse.country_code = 'TH'; warehouse.save()
    assert edit(context, job, {'warehouse_id': warehouse.pk}).status_code == 400


def test_store_order_conflict_stays_pending_and_order_matching_is_separate(context):
    job = parsed(context)
    user, store = context[1:3]
    order = SalesOrder.objects.get(tenant=user.tenant, store=store, external_order_id='ORDER001')
    other_store = type(store).objects.create(tenant=user.tenant, platform=store.platform,
        code='SPOTHER', name='另一店铺', country_code='PH')
    assert edit(context, job, {'store_id': other_store.pk}).status_code == 200
    row = job.rows.get(number=1)
    assert row.status == 'error' and '订单' in row.error
    job.refresh_from_db()
    assert edit(context, job, {'store_id': store.pk}).status_code == 200
    preview = context[0].get(URL + str(job.pk) + '/').data['data']
    assert preview['results'][0]['match_status'] == 'matched'
    assert not WarehouseFee.objects.exists()


def test_batch_is_atomic_and_requires_reason_for_ownership_changes(context):
    job = parsed(context)
    assert edit(context, job, {'amount': '4'}, reason='').status_code == 400
    before = list(job.rows.order_by('number').values_list('data', flat=True))
    response = edit(context, job, rows=[
        {'number': 1, 'changes': {'fee_item': '补录处理费'}},
        {'number': 999, 'changes': {'fee_item': '不存在'}},
    ])
    assert response.status_code == 400
    assert list(job.rows.order_by('number').values_list('data', flat=True)) == before


@pytest.mark.parametrize('status', ['parsing', 'importing', 'completed'])
def test_running_completed_and_partially_imported_jobs_are_locked(context, status):
    job = parsed(context)
    job.status = status; job.save()
    assert edit(context, job, {'note': '不应保存'}).status_code == 400


def test_stale_private_partial_and_revoked_edits_are_blocked(context):
    job = parsed(context)
    assert edit(context, job, {'note': '旧预览'}, version=0).status_code == 400
    other = user_for(context[1].tenant, 'other-row-editor'); grant(other, 'finance.warehouse_fees.import')
    assert client_for(other).post(URL + str(job.pk) + '/', {
        'operation': 'edit', 'version': 1, 'rows': [{'number': 1, 'changes': {'note': '不属于本人'}}],
    }, format='json').status_code == 404
    job.rows.filter(number=2).update(status='existing')
    assert edit(context, job, {'note': '部分已导入'}).status_code == 400
    context[1].is_active = False; context[1].save()
    assert edit(context, job, {'note': '失效账号'}).status_code in {401, 403}


def test_edited_import_is_idempotent_and_cannot_be_edited_afterwards(context):
    job = parsed(context)
    assert edit(context, job, {'note': '核实后导入'}).status_code == 200
    job.refresh_from_db()
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = context[0].post(URL + str(job.pk) + '/', {
            'operation': 'import', 'version': job.version, 'valid_only': False,
        }, format='json')
    assert response.status_code == 202
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'import')
    assert WarehouseFee.objects.count() == 2
    fee = WarehouseFee.objects.get(kind='order')
    assert fee.note == '核实后导入' and fee.source['original_data']['external_order_id'] == 'ORDER001'
    process_job(str(job.pk), job.version, 'import')
    assert WarehouseFee.objects.count() == 2
    job.refresh_from_db()
    assert edit(context, job, {'note': '已导入不可改'}).status_code == 400


def test_legacy_preview_recovers_originals_from_file_and_exposes_private_audit(context):
    job = parsed(context)
    for row in job.rows.all():
        row.source.pop('original_data'); row.source.pop('parser_issues'); row.save()
    assert edit(context, job, {'note': '兼容历史预览'}).status_code == 200
    row = job.rows.get(number=1)
    assert row.source['original_data']['note'] != '兼容历史预览'
    audit = context[0].get(URL + str(job.pk) + '/', {'audit_row': 1})
    assert audit.status_code == 200
    assert audit.data['data']['results'][0]['detail']['before']['note'] == row.source['original_data']['note']
    assert audit.data['data']['results'][0]['actor'] == context[1].pk


def test_duplicate_effective_rows_stay_pending(context):
    job = parsed(context)
    row = job.rows.get(number=1)
    row.pk = None; row.number = 3; row.source = {**row.source, 'row': 99}; row.save()
    assert edit(context, job, {'note': '重新核对'}).status_code == 200
    assert job.rows.filter(number__in=[1, 3], status='error').count() == 2
    assert '重复' in job.rows.get(number=3).error


def test_source_issues_and_scientific_order_repair_do_not_bypass_invoice_control(context):
    order = SalesOrder.objects.get(tenant=context[1].tenant, external_order_id='ORDER001')
    order.external_order_id = '00001234567890123456'; order.save()
    job = parsed(context, ph_bill(context[2].code, context[3].code, order='1.23E+18'))
    assert job.rows.get(number=1).status == 'error'
    assert edit(context, job, {'external_order_id': '00001234567890123456'}).status_code == 200
    row = job.rows.get(number=1)
    assert row.status == 'valid', row.error
    assert row.source['original_data']['external_order_id'] == '1.23E+18'


def test_note_only_edit_keeps_unaffected_values(context):
    job = parsed(context)
    before_other = job.rows.get(number=2).data
    assert edit(context, job, {'note': '只修正备注'}).status_code == 200
    assert job.rows.get(number=2).data == before_other
    assert not WarehouseFee.objects.exists()


def test_other_fee_amount_or_currency_changes_keep_reconciliation_difference_visible(context):
    job = parsed(context)
    assert edit(context, job, rows=[{'number': 2, 'changes': {'amount': '9.000000'}}]).status_code == 200
    assert job.rows.get(number=2).status == 'valid'
    job.refresh_from_db()
    assert job.summary['corrected_other_difference'] == '-1.000000'
    job.refresh_from_db()
    assert edit(context, job, rows=[{'number': 2}], operation='restore').status_code == 200
    assert job.rows.get(number=2).status == 'valid'


def test_existing_fee_changed_content_is_held_before_import(context):
    from apps.finance.warehouse_fee_services import create_fee
    job = parsed(context)
    row = job.rows.get(number=1)
    create_fee(context[1], row.data, action='import', source=row.source)
    assert edit(context, job, {'note': '与已有草稿不同'}).status_code == 200
    assert job.rows.get(number=1).status == 'error'
    assert '已登记但内容不同' in job.rows.get(number=1).error


def test_reparse_source_conflict_does_not_silently_apply_saved_correction(context):
    job = parsed(context)
    assert edit(context, job, {'note': '修正值'}).status_code == 200
    job.refresh_from_db()
    edits = job.overrides['_row_edits']
    next(iter(edits.values()))['signature'] = 'different-source'
    job.save()
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = context[0].post(URL + str(job.pk) + '/', {'operation': 'parse', 'version': job.version}, format='json')
    assert response.status_code == 202
    job.refresh_from_db(); process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.summary['correction_warning']
    assert job.rows.get(number=1).data['note'] != '修正值'
    assert context[0].post(URL + str(job.pk) + '/', {'operation': 'import', 'version': job.version, 'valid_only': True}, format='json').status_code == 400


def test_changing_business_key_cannot_duplicate_an_already_imported_source(context):
    from apps.finance.warehouse_fee_services import create_fee
    job = parsed(context)
    row = job.rows.get(number=1)
    create_fee(context[1], row.data, action='import', source=row.source)
    assert edit(context, job, {'fee_item': '另一项目名'}).status_code == 200
    assert '原账单该行已有导入记录' in job.rows.get(number=1).error
    assert WarehouseFee.objects.count() == 1


def test_batch_amount_changes_are_rejected_by_backend_too(context):
    job = parsed(context)
    assert edit(context, job, rows=[{'number': 1, 'changes': {'amount': '4'}}, {'number': 2, 'changes': {'amount': '8'}}]).status_code == 400
