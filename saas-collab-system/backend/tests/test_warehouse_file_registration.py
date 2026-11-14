import json
import csv
import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.finance.warehouse_bill_contract import POLICY
from apps.finance.warehouse_bill_formats import clean_config, parse_mapped
from apps.finance.warehouse_bill_parser import BillError
from apps.finance.warehouse_bill_uploads import process_job
from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from tests.test_sales_management import grant, create_scope, user_for, client_for
from tests.test_warehouse_bill_uploads import context, URL, workbook


def config():
    return {'schema_version': 3, 'sheets': [
        {'name': '订单明细', 'kind': 'order', 'header': 1, 'columns': {'number': 'A', 'amount': 'B'},
         'expected': {'A': '订单号', 'B': '金额'}},
        {'name': '结算单', 'kind': 'settlement', 'header': 1, 'columns': {'item': 'A', 'amount': 'B'},
         'expected': {'A': '项目', 'B': '金额'}, 'items': {'处理费': {'role': 'order'},
          '仓租': {'role': 'other'}, '其他应收': {'role': 'ignore', 'reason': '核对后统一补差'}, '总额': {'role': 'total'}}}]}


def raw(difference='0', order='4'):
    return workbook({'订单明细': [['订单号', '金额'], ['ORDER001', order]],
        '结算单': [['项目', '金额'], ['处理费', 4], ['仓租', 6], ['其他应收', difference], ['总额', str(Decimal(10) + Decimal(difference))]]})


def upload(context, difference='0', order='4'):
    client, user, _, warehouse = context
    grant(user, 'finance.warehouse_fees.register')
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL, {'file': SimpleUploadedFile('2026年9月菲律宾.xlsx', raw(difference, order)),
            'options': json.dumps({'registration_mode': POLICY, 'format_config': config(),
                'warehouse_id': warehouse.pk, 'bill_month': '2026-09'})}, format='multipart')
    assert response.status_code == 202, response.data
    job = WarehouseBillUpload.objects.get(pk=response.data['data']['id'])
    process_job(str(job.pk), job.version, 'parse'); job.refresh_from_db()
    assert job.status == 'ready', job.error
    return job


@pytest.mark.django_db
def test_selected_drafts_do_not_register_or_generate_difference_even_when_batch_blocked(context):
    client, _, _, _ = context
    job = upload(context, '2', order='7')
    assert job.summary['validation']['blocking']
    original_difference = job.summary['net_difference']
    endpoint = URL + str(job.pk) + '/'
    payload = {'operation': 'save_drafts', 'version': job.version, 'rows': [2]}
    response = client.post(endpoint, payload, format='json')
    assert response.status_code == 200, response.data
    assert WarehouseFee.objects.count() == 1
    assert WarehouseFee.objects.get().status == 'draft'
    assert job.rows.get(number=1).fee_id is None
    job.refresh_from_db()
    assert 'file_confirmation' not in job.summary
    assert job.summary['net_difference'] == original_difference
    assert client.post(endpoint, payload, format='json').status_code == 400
    payload['version'] = job.version
    assert client.post(endpoint, payload, format='json').status_code == 200
    assert WarehouseFee.objects.count() == 1


@pytest.mark.django_db
def test_full_file_flow_edit_save_register_and_retry_preserves_original_control(context):
    client, user, _, _ = context
    grant(user, 'finance.warehouse_fees.edit')
    job = upload(context, '2')
    endpoint = URL + str(job.pk) + '/'
    assert WarehouseFee.objects.count() == 0
    assert job.rows.get(number=1).source['matching']['status'] == 'matched'
    result = client.post(endpoint, {'operation':'edit','version':job.version,
        'rows':[{'number':1,'changes':{'amount':'3.123456'}}],'reason':'功能验收：调整计费'}, format='json')
    assert result.status_code == 200, result.data
    job.refresh_from_db()
    assert job.summary['net_difference'] == '2.876544'
    result = client.post(endpoint, {'operation':'save_drafts','version':job.version,'rows':[1]}, format='json')
    assert result.status_code == 200, result.data
    assert WarehouseFee.objects.count() == 1
    fee = WarehouseFee.objects.get()
    assert fee.status == 'draft' and fee.amount == Decimal('3.123456')
    job.refresh_from_db()
    result = client.post(endpoint, {'operation':'register','version':job.version,'rows':[1,2],
        'coverage_confirmed':True,'difference_confirmed':True}, format='json')
    assert result.status_code == 200, result.data
    assert WarehouseFee.objects.filter(status='registered').count() == 3
    assert WarehouseFee.objects.get(fee_item='处理费差额').amount == Decimal('2.876544')
    assert sum(WarehouseFee.objects.values_list('amount', flat=True)) == Decimal('12')
    job.refresh_from_db()
    result = client.post(endpoint, {'operation':'register','version':job.version,'rows':[1,2],
        'coverage_confirmed':True,'difference_confirmed':True}, format='json')
    assert result.status_code == 200, result.data
    assert WarehouseFee.objects.count() == 3


@pytest.mark.django_db
def test_parser_publishes_reading_and_matching_before_ready(context):
    from apps.finance.warehouse_bill_formats import parse_new_bill
    job = upload(context)
    job.status = 'queued'; job.save(update_fields=['status'])
    stages = []
    original_normalize = __import__('apps.finance.warehouse_bill_uploads', fromlist=['normalize_rows']).normalize_rows
    def parsing(*args, **kwargs):
        kwargs['progress']('订单明细', 10000)
        current = WarehouseBillUpload.objects.get(pk=job.pk)
        assert current.status == 'parsing'
        assert current.summary['progress'] == {'stage':'reading','sheet':'订单明细','scanned':10000,'total':None}
        stages.append('reading')
        return parse_new_bill(*args, **kwargs)
    def matching(*args, **kwargs):
        current = WarehouseBillUpload.objects.get(pk=job.pk)
        assert current.summary['progress']['stage'] == 'matching'
        assert current.summary['progress']['total'] == 2
        stages.append('matching')
        yield from original_normalize(*args, **kwargs)
    with patch('apps.finance.warehouse_bill_formats.parse_new_bill', side_effect=parsing), patch(
            'apps.finance.warehouse_bill_uploads.normalize_rows', side_effect=matching):
        process_job(str(job.pk), job.version, 'parse')
    job.refresh_from_db()
    assert stages == ['reading', 'matching']
    assert job.status == 'ready' and job.processed == 2
    assert 'progress' not in job.summary
    assert WarehouseFee.objects.count() == 0


@pytest.mark.django_db
def test_selected_drafts_reject_invalid_selection_atomically(context):
    client, _, _, _ = context
    job = upload(context)
    endpoint = URL + str(job.pk) + '/'
    for numbers in ([], [1, 1], [1, 999], [True], ['1']):
        response = client.post(endpoint, {'operation': 'save_drafts', 'version': job.version, 'rows': numbers}, format='json')
        assert response.status_code == 400
        assert WarehouseFee.objects.count() == 0


@pytest.mark.django_db
def test_all_original_issues_are_paginated_and_exported(context):
    client, _, _, _ = context
    job = upload(context)
    findings = [{'code': 'invalid_amount', 'level': 'row', 'sheet': '订单明细',
                 'row': number + 2, 'field': 'amount', 'message': f'金额待核对-{number}'}
                for number in range(205)]
    job.summary['validation'] = {'blocking': True, 'count': 205, 'items': findings}
    job.save(update_fields=['summary'])
    endpoint = URL + str(job.pk) + '/'
    pages = [client.get(endpoint, {'issues_page': number}).data['data'] for number in (1, 2, 3)]
    assert [len(page['results']) for page in pages] == [100, 100, 5]
    assert [item for page in pages for item in page['results']] == findings
    exported = client.get(endpoint + 'errors/')
    assert exported.status_code == 200
    rows = list(csv.reader(io.StringIO(b''.join(exported.streaming_content).decode('utf-8-sig'))))
    assert len(rows) == 206
    assert rows[-1][0:2] == ['订单明细', '206']
    assert rows[-1][-1].endswith('金额待核对-204')


@pytest.mark.django_db
@pytest.mark.parametrize('difference, expected', [('0', 0), ('0.004999', 0), ('0.005000', 1), ('2', 1)])
def test_only_selected_rows_register_and_net_supplement_is_idempotent(context, difference, expected):
    client, user, _, _ = context
    job = upload(context, difference)
    assert not job.summary['validation']['blocking'], job.summary
    endpoint = URL + str(job.pk) + '/'
    data = {'operation': 'register', 'version': job.version, 'rows': [1], 'coverage_confirmed': True}
    if expected:
        assert client.post(endpoint, data, format='json').status_code == 400
        assert WarehouseFee.objects.count() == 0
    data['difference_confirmed'] = True
    response = client.post(endpoint, data, format='json')
    assert response.status_code == 200, response.data
    assert WarehouseFee.objects.count() == 1 + expected
    assert WarehouseFee.objects.filter(status='registered').count() == 1 + expected
    assert client.post(endpoint, data, format='json').status_code == 400  # stale version
    job.refresh_from_db(); data['version'] = job.version
    assert client.post(endpoint, data, format='json').status_code == 200
    assert WarehouseFee.objects.count() == 1 + expected
    job.refresh_from_db()
    assert Decimal(job.summary['net_difference']) == Decimal(difference)


@pytest.mark.django_db
@pytest.mark.parametrize('difference, order', [('-0.004999', '4'), ('-0.005000', '4'), ('0', '5'), ('0', None)])
def test_batch_blocking_rejects_registration(context, difference, order):
    client, _, _, _ = context
    job = upload(context, difference, order)
    assert job.summary['validation']['blocking']
    response = client.post(URL + str(job.pk) + '/', {'operation':'register', 'version':job.version,
        'rows':[2], 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
    assert response.status_code == 400
    assert WarehouseFee.objects.count() == 0


@pytest.mark.django_db
def test_processing_difference_registers_once_without_using_selected_total(context):
    client, _, _, _ = context
    job = upload(context, order='3')
    assert not job.summary['validation']['blocking']
    assert job.summary['processing_difference'] == '1.000000'
    assert WarehouseFee.objects.count() == 0
    endpoint = URL + str(job.pk) + '/'
    for selected in ([2], [1], [1, 2]):
        result = client.post(endpoint, {'operation':'register', 'version':job.version,
            'rows':selected, 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
        assert result.status_code == 200, result.data
        job.refresh_from_db()
        assert WarehouseFee.objects.filter(fee_item='处理费差额').count() == 1
        assert WarehouseFee.objects.get(fee_item='处理费差额').amount == Decimal('1')
    assert sum(WarehouseFee.objects.values_list('amount', flat=True)) == Decimal('10')


@pytest.mark.django_db
def test_other_fee_edit_recalculates_single_supplement(context):
    client, user, _, _ = context
    grant(user, 'finance.warehouse_fees.edit')
    job = upload(context, '2')
    endpoint = URL + str(job.pk) + '/'
    response = client.post(endpoint, {'operation':'edit','version':job.version,
        'rows':[{'number':2,'changes':{'amount':'5'}}], 'reason':'核对其他费用'}, format='json')
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.summary['processing_difference'] == '3.000000'
    response = client.post(endpoint, {'operation':'register','version':job.version,
        'rows':[1,2], 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
    assert response.status_code == 200, response.data
    assert WarehouseFee.objects.get(fee_item='处理费差额').amount == Decimal('3')
    assert not WarehouseFee.objects.filter(fee_item='原文件结算补差').exists()
    assert sum(WarehouseFee.objects.values_list('amount', flat=True)) == Decimal('12')


@pytest.mark.django_db
def test_confirmation_failure_rolls_back_selected_fees_and_ack(context):
    client, _, _, _ = context
    job = upload(context, '2')
    with patch('apps.finance.warehouse_file_registration.supplement', side_effect=BillError('故障注入')):
        response = client.post(URL + str(job.pk) + '/', {'operation':'register', 'version':job.version,
            'rows':[1, 2], 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
    assert response.status_code == 400
    assert WarehouseFee.objects.count() == 0
    job.refresh_from_db()
    assert 'file_confirmation' not in job.summary
    assert not job.rows.filter(fee__isnull=False).exists()


@pytest.mark.django_db
def test_rule_persistence_same_tenant_and_isolation(context):
    client, user, _, warehouse = context
    endpoint = '/api/finance/warehouse-fees/format-rules/'
    data = {'name':'九月格式', 'warehouse_id':warehouse.pk, 'config':config()}
    response = client.post(endpoint, data, format='json')
    assert response.status_code == 201, response.data
    assert client.post(endpoint, data, format='json').status_code == 400
    colleague = user_for(user.tenant, 'another-importer'); grant(colleague, 'finance.warehouse_fees.import')
    assert len(client_for(colleague).get(endpoint).data['data']['results']) == 1
    tenant, _, _, _ = create_scope('isolated-format')
    outsider = user_for(tenant, 'outside-importer'); grant(outsider, 'finance.warehouse_fees.import')
    assert client_for(outsider).get(endpoint).data['data']['results'] == []
    assert client_for(outsider).post(endpoint, data, format='json').status_code == 404


@pytest.mark.parametrize('columns', [{'number': [], 'amount': 'B'}, {'number':'B','amount':'B'}])
def test_malformed_columns_return_validation_not_server_error(columns):
    supplied = config(); supplied['sheets'][0]['columns'] = columns
    with pytest.raises(BillError): clean_config(supplied)


def test_real_celery_task_dispatches_version_fenced_worker():
    from apps.finance.tasks import process_warehouse_bill
    with patch('apps.finance.warehouse_bill_uploads.process_job') as process:
        process_warehouse_bill.run('test-job', 3, 'parse')
    process.assert_called_once_with('test-job', 3, 'parse')


@pytest.mark.django_db
def test_mapped_file_drift_missing_sheet_and_new_project_rejected(context, tmp_path):
    _, _, _, warehouse = context
    path = tmp_path / 'test.xlsx'; path.write_bytes(raw())
    supplied = config(); supplied['sheets'][0]['expected']['B'] = '旧金额'
    with pytest.raises(BillError, match='表头'): parse_mapped(path, '2026年9月菲律宾.xlsx', supplied, warehouse, '2026-09')
    supplied = config(); supplied['sheets'].pop()
    with pytest.raises(BillError, match='工作表集合'): parse_mapped(path, '2026年9月菲律宾.xlsx', supplied, warehouse, '2026-09')
    supplied = config(); del supplied['sheets'][1]['items']['仓租']
    with pytest.raises(BillError, match='项目已变化'): parse_mapped(path, '2026年9月菲律宾.xlsx', supplied, warehouse, '2026-09')


@pytest.mark.django_db
def test_rule_auto_selection_scope_conflict_and_current_month(context, tmp_path):
    from apps.finance.warehouse_bill_formats import save_rule, parse_new_bill
    from apps.permissions.models import DataScope
    client, user, _, warehouse = context
    rule = save_rule(user, {'name':'原表规则', 'warehouse_id':warehouse.pk, 'config':config()})
    path = tmp_path / 'rule.xlsx'; path.write_bytes(raw())
    _, summary = parse_new_bill(user, path, '2026年10月菲律宾.xlsx', {})
    assert summary['applied_rule']['id'] == rule.pk and summary['bill_month'] == '2026-10'
    assert rule.version == 2 and rule.config['schema_version'] == 3
    save_rule(user, {'name':'重复格式另一版本', 'warehouse_id':warehouse.pk, 'config':config()})
    with pytest.raises(BillError, match='多个格式规则'):
        parse_new_bill(user, path, '2026年10月菲律宾.xlsx', {})
    _, summary = parse_new_bill(user, path, '2026年10月菲律宾.xlsx', {'format_rule_id':rule.pk})
    assert summary['applied_rule']['id'] == rule.pk
    restricted = user_for(user.tenant, 'restricted-format-user')
    grant(restricted, 'finance.warehouse_fees.import', DataScope.ScopeType.CUSTOM, {'warehouse_ids':[warehouse.pk+9999]})
    assert client_for(restricted).get('/api/finance/warehouse-fees/format-rules/').data['data']['results'] == []
    with pytest.raises(BillError): parse_new_bill(restricted, path, '2026年10月菲律宾.xlsx', {'format_rule_id':rule.pk})


@pytest.mark.django_db
def test_editing_amount_recalculates_difference_and_preserves_precision(context):
    client, user, _, _ = context
    grant(user, 'finance.warehouse_fees.edit')
    job = upload(context, '2')
    response = client.post(URL + str(job.pk) + '/', {'operation':'edit','version':job.version,
        'rows':[{'number':1,'changes':{'amount':'4.123456'}}],'reason':'核对原计费'},format='json')
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.rows.get(number=1).status == 'valid'
    assert job.summary['net_difference'] == '1.876544'
    assert job.rows.get(number=1).data['amount'] == '4.123456'
    response = client.post(URL + str(job.pk) + '/', {'operation':'edit','version':job.version,
        'rows':[{'number':1,'changes':{'note':'补充说明'}}],'reason':'补充说明'},format='json')
    assert response.status_code == 200, response.data
    assert job.rows.get(number=1).data['amount'] == '4.123456'


@pytest.mark.django_db
def test_changed_source_during_parse_fails_without_rows(context):
    from apps.finance.warehouse_bill_uploads import source_path
    from apps.finance.warehouse_bill_formats import parse_new_bill
    client, _, _, _ = context
    job = upload(context)
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL + str(job.pk) + '/', {'operation':'parse','version':job.version,'options':job.overrides},format='json')
    assert response.status_code == 202
    job.refresh_from_db()
    def changed(*args, **kwargs):
        result = parse_new_bill(*args, **kwargs)
        with source_path(job).open('ab') as stream: stream.write(b'changed-in-test')
        return result
    with patch('apps.finance.warehouse_bill_formats.parse_new_bill', side_effect=changed):
        process_job(str(job.pk),job.version,'parse')
    job.refresh_from_db()
    assert job.status == 'failed'
    assert WarehouseFee.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_mysql_parallel_confirmation_creates_one_supplement(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, close_old_connections
    from rest_framework.exceptions import ValidationError
    from apps.finance.warehouse_file_registration import confirm_rows
    from apps.accounts.models import CustomUser
    if connection.vendor != 'mysql': pytest.skip('Requires isolated MySQL transaction test')
    _, user, _, _ = context
    job = upload(context,'2')
    barrier = Barrier(2)
    payload = {'version':job.version,'rows':[1,2],'coverage_confirmed':True,'difference_confirmed':True}
    def submit():
        close_old_connections()
        try:
            actor = CustomUser.objects.get(pk=user.pk)
            batch = WarehouseBillUpload.objects.get(pk=job.pk)
            barrier.wait(timeout=20)
            confirm_rows(actor,batch,payload)
            return 'registered'
        except ValidationError: return 'version_conflict'
        finally: close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _:submit(),range(2)))
    assert sorted(outcomes) == ['registered','version_conflict']
    assert WarehouseFee.objects.count() == 3
    assert WarehouseFee.objects.filter(source__type='warehouse_file_supplement').count() == 1
