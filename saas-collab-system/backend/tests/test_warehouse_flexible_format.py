from copy import deepcopy
import pytest
from apps.finance.warehouse_bill_parser import BillError
from apps.finance.warehouse_bill_rule_resolution import resolve_config, editable_config
from apps.finance.warehouse_bill_formats import clean_config


def layout():
    config = {'schema_version':3,'sheets':[
        {'name':'代发费','kind':'order','header':1,'columns':{'number':'A','amount':'H'},
         'expected':{'A':'平台订单号','H':'实际应收','I':'是否含哑铃'},'header_mode':'fields'},
        {'name':'结算','kind':'settlement','header':1,'start':2,'end':3,
         'columns':{'item':'H','amount':'G'},'expected':{'A':'序号','G':'总金额','H':'备注'},
         'header_mode':'fields','settlement_auto':'sequence_total','total_source':'G9',
         'items':{'代发费':{'role':'order'},'仓租':{'role':'other'}}},
        {'name':'已知辅助','kind':'ignore','reason':'不参与取数','optional_sheet':True}]}
    samples=[{'name':'代发费','sample':[{'row':3,'cells':{'C':'平台订单号','D':'实际应收','I':'是否瑜伽服'}}]},
        {'name':'结算','sample':[
            {'row':6,'cells':{'B':'序号','H':'总金额','I':'备注'}},
            {'row':7,'cells':{'B':1,'H':10,'I':'代发费'}},
            {'row':8,'cells':{'B':2}},
            {'row':14,'cells':{'H':10}}]}]
    return config,samples


def test_required_fields_move_and_missing_known_auxiliary_does_not_change_template():
    config,samples=layout();original=deepcopy(config)
    clean_config(config)
    result=resolve_config(config,samples)
    assert result['sheets'][0]['columns']=={'number':'C','amount':'D'}
    assert result['sheets'][0]['header']==3
    assert result['sheets'][1]['total_source']=='H14'
    assert result['sheets'][1]['items']=={'代发费':{'role':'order'}}
    assert config==original
    edited=editable_config(config,samples)
    assert edited['sheets'][1]['items']==original['sheets'][1]['items']
    assert any(s.get('optional_sheet') for s in edited['sheets'])


@pytest.mark.parametrize('change',['duplicate_total','missing_amount','duplicate_amount','unknown_item','unknown_sheet','unnumbered_fee'])
def test_flexible_layout_still_rejects_ambiguous_or_unclassified_data(change):
    config,samples=layout()
    if change=='duplicate_total':samples[1]['sample'].append({'row':15,'cells':{'H':10}})
    if change=='missing_amount':samples[0]['sample'][0]['cells'].pop('D')
    if change=='duplicate_amount':samples[0]['sample'][0]['cells']['E']='实际应收'
    if change=='unknown_item':samples[1]['sample'][1]['cells']['I']='新收费'
    if change=='unknown_sheet':samples.append({'name':'未知费用','sample':[]})
    if change=='unnumbered_fee':samples[1]['sample'].append({'row':10,'cells':{'H':5,'I':'仓租'}})
    with pytest.raises(BillError):resolve_config(config,samples)


def test_sequence_total_keeps_original_total_when_projects_disagree():
    config,samples=layout();samples[1]['sample'][1]['cells']['H']=15
    result=resolve_config(config,samples)
    assert result['sheets'][1]['total_source']=='H14'


def test_explicit_field_and_sheet_aliases_survive_editing_without_accepting_unknown_names():
    config,samples=layout()
    spec=config['sheets'][0]
    spec['sheet_aliases']=['历史代发费']
    spec['field_aliases']={'A':['外部订单号']}
    samples[0]['name']='历史代发费'
    samples[0]['sample'][0]['cells']['C']='外部订单号'
    result=resolve_config(clean_config(config),samples)
    edited=editable_config(config,samples)
    assert resolve_config(clean_config(edited),samples)==result
    samples[0]['name']='未知表'
    with pytest.raises(BillError):resolve_config(config,samples)


def test_only_explicit_optional_filter_may_be_absent():
    config,samples=layout()
    spec=config['sheets'][0]
    spec['filters']=[{'column':'J','values':['outbound'],'optional':True}]
    spec['expected']['J']='类型'
    assert resolve_config(config,samples)['sheets'][0]['filters']==[]
    spec['filters'][0].pop('optional')
    with pytest.raises(BillError):resolve_config(config,samples)


def test_new_label_total_logic_previews_items_without_a_manually_entered_end(tmp_path):
    from tests.test_warehouse_bill_uploads import workbook
    from apps.finance.warehouse_bill_formats import inspect_file
    p=tmp_path/'new.xlsx'
    p.write_bytes(workbook({'结算':[['标题'],[],['项目','金额'],['处理费',10],['仓租',2],['合计',12]]}))
    result=inspect_file(p,{'name':'结算','kind':'settlement','header':3,'end':None,
        'columns':{'item':'A','amount':'B'},'header_mode':'fields','settlement_auto':'total_row'})
    assert result['range']['end']==5
    assert result['range']['total_source']=='B6'
    assert [r['item'] for r in result['items']]==['处理费','仓租']


def test_total_label_outside_item_column_and_with_month_prefix_is_supported(tmp_path):
    from tests.test_warehouse_bill_uploads import workbook
    from apps.finance.warehouse_bill_formats import inspect_file
    p=tmp_path/'bill.xlsx'
    p.write_bytes(workbook({'汇总':[['序列','计费名称','人民币'],[1,'代发费',10],
        [2,'仓租',2],['2026年10月HY仓库费用合计',None,12]]}))
    spec={'name':'汇总','kind':'settlement','header':1,'end':None,
        'columns':{'item':'B','amount':'C'},'header_mode':'fields','settlement_auto':'total_row'}
    result=inspect_file(p,spec)
    assert result['range']['total_source']=='C4'
    assert [r['item'] for r in result['items']]==['代发费','仓租']
    from apps.finance.warehouse_bill_rule_resolution import labelled_total_rows
    assert labelled_total_rows({4:{'A':'费用合计','C':12},5:{'B':'总计','C':12}},1,'C')==[4,5]


from tests.test_warehouse_bill_uploads import context


@pytest.mark.django_db
def test_mixed_order_warehouses_register_details_once_and_leave_difference_pending(context):
    import json
    from unittest.mock import patch
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.commerce.models import SalesOrder
    from apps.masterdata.models import WarehouseMaster
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup
    from apps.finance.warehouse_bill_uploads import process_job
    from apps.finance.warehouse_fee_models import WarehouseBillUpload, WarehouseFee
    from tests.test_warehouse_bill_uploads import URL, workbook
    from tests.test_warehouse_file_registration import config
    from tests.test_sales_management import grant
    client,user,_,wh=context
    grant(user,'finance.warehouse_fees.register')
    wh2=WarehouseMaster.objects.create(tenant=user.tenant,code='SECOND',name='第二仓',country_code='PH')
    first=SalesOrder.objects.get(tenant=user.tenant,external_order_id='ORDER001')
    OrderWarehouseLookup.objects.create(order=first,warehouse=wh,status='matched')
    first.pk=None;first.external_order_id='ORDER002';first.save()
    OrderWarehouseLookup.objects.create(order=first,warehouse=wh2,status='matched')
    data=workbook({'订单明细':[['订单号','金额'],['ORDER001',4],['ORDER002',4]],
        '结算单':[['项目','金额'],['处理费',8],['仓租',6],['其他应收',2],['总额',16]]})
    with patch('apps.finance.warehouse_bill_uploads.enqueue'):
        response=client.post(URL,{'file':SimpleUploadedFile('mixed.xlsx',data),
            'options':json.dumps({'registration_mode':'file_settlement_v2','order_warehouse':True,
                'country':'PH','bill_month':'2026-09','warehouse_id':wh.pk,'format_config':config()})},format='multipart')
    assert response.status_code==202,response.data
    job=WarehouseBillUpload.objects.get(pk=response.data['data']['id'])
    process_job(str(job.pk),job.version,'parse');job.refresh_from_db()
    assert job.status=='ready',job.error
    assert job.summary['mixed_warehouses'] and job.summary['settlement_warehouse_id'] is None
    assert set(job.rows.filter(data__kind='order').values_list('data__warehouse_id',flat=True))=={wh.pk,wh2.pk}
    premature = client.post(URL+str(job.pk)+'/',{'operation':'allocate_difference','version':job.version,
        'allocations':[{'warehouse_id':wh.pk,'amount':'2'}], 'reason':'核对归属',
        'coverage_confirmed':True,'difference_confirmed':True},format='json')
    assert premature.status_code == 400
    assert WarehouseFee.objects.count() == 0
    for _ in range(2):
        response=client.post(URL+str(job.pk)+'/',{'operation':'register','version':job.version,
            'rows':[1,2,3],'coverage_confirmed':True,'difference_confirmed':True},format='json')
        assert response.status_code==200,response.data
        job.refresh_from_db()
    assert job.summary['file_confirmation']['difference_pending'] is True
    assert WarehouseFee.objects.count()==3
    assert not WarehouseFee.objects.filter(source__type='warehouse_file_supplement').exists()
    payload = {'operation':'allocate_difference','version':job.version,
        'allocations':[{'warehouse_id':wh.pk,'amount':'1.25'},{'warehouse_id':wh2.pk,'amount':'0.75'}],
        'reason':'按核对后的仓库归属分配','coverage_confirmed':True,'difference_confirmed':True}
    bad = {**payload,'allocations':[{'warehouse_id':wh.pk,'amount':'1'}]}
    assert client.post(URL+str(job.pk)+'/',bad,format='json').status_code == 400
    assert WarehouseFee.objects.count() == 3
    for allocations in [[{'warehouse_id':999999,'amount':'2'}],
            [{'warehouse_id':wh.pk,'amount':'NaN'}],
            [{'warehouse_id':wh.pk,'amount':'1'},{'warehouse_id':wh.pk,'amount':'1'}]]:
        assert client.post(URL+str(job.pk)+'/',{**payload,'allocations':allocations},format='json').status_code == 400
    assert client.post(URL+str(job.pk)+'/',{**payload,'difference_confirmed':False},format='json').status_code == 400
    assert WarehouseFee.objects.count() == 3
    for _ in range(2):
        payload['version'] = job.version
        response = client.post(URL+str(job.pk)+'/',payload,format='json')
        assert response.status_code == 200,response.data
        job.refresh_from_db()
    assert WarehouseFee.objects.count() == 5
    assert job.summary['file_confirmation']['difference_pending'] is False
    assert set(WarehouseFee.objects.filter(source__type='warehouse_file_supplement').values_list('warehouse_id','amount')) == {(wh.pk, __import__('decimal').Decimal('1.25')),(wh2.pk,__import__('decimal').Decimal('0.75'))}
    payload['version'] = job.version
    payload['allocations'] = [{'warehouse_id':wh.pk,'amount':'2'}]
    assert client.post(URL+str(job.pk)+'/',payload,format='json').status_code == 400


def test_overlapping_field_aliases_cannot_share_a_physical_column():
    config, samples = layout()
    config['sheets'][0]['field_aliases'] = {'A':['共同字段'], 'H':['共同字段']}
    samples[0]['sample'][0]['cells'] = {'C':'共同字段'}
    with pytest.raises(BillError, match='同一列'):
        resolve_config(config, samples)


def test_renamed_optional_filter_is_not_silently_removed():
    config, samples = layout()
    spec = config['sheets'][0]
    spec['filters'] = [{'column':'J','values':['outbound'],'optional':True}]
    spec['expected']['J'] = '类型'
    samples[0]['sample'][0]['cells']['J'] = '费用类别'
    with pytest.raises(BillError, match='可选筛选字段'):
        resolve_config(config, samples)


def test_settlement_total_after_row_40_is_resolved_and_previewed(tmp_path):
    from tests.test_warehouse_bill_uploads import workbook
    from apps.finance.warehouse_bill_formats import inspect_file, resolution_samples
    p = tmp_path / 'long.xlsx'
    p.write_bytes(workbook({'结算':[['项目','金额'],['处理费',10]] + [[] for _ in range(52)] + [['合计',10]]}))
    spec = {'name':'结算','kind':'settlement','header':1,'columns':{'item':'A','amount':'B'},
        'expected':{'A':'项目','B':'金额'},'header_mode':'fields','settlement_auto':'total_row',
        'items':{'处理费':{'role':'order'}}}
    config = {'schema_version':3,'sheets':[spec]}
    assert resolve_config(config, resolution_samples(p, config))['sheets'][0]['total_source'] == 'B55'
    assert inspect_file(p,spec)['range']['total_source'] == 'B55'
