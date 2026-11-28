"""Opt-in real workbook acceptance; all registrations use pytest's isolated DB."""
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.finance.warehouse_bill_contract import POLICY
from apps.finance.warehouse_bill_uploads import process_job
from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from apps.masterdata.models import CountrySiteMaster
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for
from tests.test_warehouse_bill_uploads import URL


@pytest.mark.django_db
def test_october_my_original_file_registration(settings, tmp_path):
    path = os.environ.get('WAREHOUSE_REAL_MY_BILL')
    if not path:
        pytest.skip('Requires private original workbook; no business file committed.')
    settings.BASE_DIR = tmp_path
    tenant, _, store, warehouse = create_scope('real-my-bill', currency='MYR', country='MY')
    warehouse.code = 'MY-A1'; warehouse.save()
    CountrySiteMaster.objects.create(tenant=tenant, code='MY', name='Malaysia', country_code='MY', currency='MYR')
    user = user_for(tenant, 'real-file-test')
    for permission in ('import', 'register', 'edit'):
        grant(user, 'finance.warehouse_fees.' + permission)
    # Only the five order identities found in the local preview are fixtures.
    # Do not invent matching orders for the remaining source rows.
    for number in ('26092882K360Q9', '261003KXQANCED', '261003KVCAAEY2', '2610096DJJA9TP', '261011CB05XK49'):
        order = create_order(tenant, store, number)
        order.external_order_id = number
        order.save(update_fields=['external_order_id'])
    client = client_for(user)
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response = client.post(URL, {
            'file': SimpleUploadedFile('2026年10月马来订单处理费老仓.xlsx', Path(path).read_bytes()),
            'options': json.dumps({'registration_mode': POLICY, 'warehouse_id': warehouse.pk,
                                  'bill_month':'2026-10', 'country':'MY'})}, format='multipart')
    assert response.status_code == 202, response.data
    job = WarehouseBillUpload.objects.get(pk=response.data['data']['id'])
    process_job(str(job.pk), job.version, 'parse')
    job.refresh_from_db()
    assert job.status == 'ready', job.error
    assert job.processed == 3043
    assert job.summary['effective_order_total'] == '6766.600000'
    assert job.summary['effective_other_total'] == '3234.636984'
    assert job.summary['processing_difference'] == '72.000000'
    assert not job.summary['validation']['blocking']
    assert job.rows.filter(status='valid').count() == 7
    assert job.rows.filter(status='error').count() == 3036
    assert WarehouseFee.objects.count() == 0
    endpoint = URL + str(job.pk) + '/'
    invalid = job.rows.filter(status='error').first()
    response = client.post(endpoint, {'operation':'register','version':job.version,
        'rows':[invalid.number], 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
    assert response.status_code == 400
    assert WarehouseFee.objects.count() == 0
    valid = list(job.rows.filter(status='valid').values_list('number', flat=True))
    for selected in (valid[:3], valid[3:], valid):
        response = client.post(endpoint, {'operation':'register','version':job.version,
            'rows':selected, 'coverage_confirmed':True, 'difference_confirmed':True}, format='json')
        assert response.status_code == 200, response.data
        job.refresh_from_db()
        supplements = WarehouseFee.objects.filter(fee_item='处理费差额')
        assert supplements.count() == 1
        assert supplements.get().amount == Decimal('72')
    assert WarehouseFee.objects.filter(status='registered').count() == 8
    assert sum(WarehouseFee.objects.values_list('amount', flat=True)) == Decimal('3319.136984')
    assert job.rows.filter(status='error', fee__isnull=True).count() == 3036
    assert not WarehouseFee.objects.filter(fee_item='原文件结算补差').exists()
