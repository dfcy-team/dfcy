from unittest.mock import patch
import pytest
from apps.integrations.feishu_reports import build_report
from apps.integrations.feishu_report_cards import report_chart_card
from tests.test_sales_realtime_board import _fixture

@pytest.mark.django_db
def test_unmapped_inventory_does_not_block_available_snapshot():
    user, tenant, platform, store, run, client = _fixture('partial-stock')
    section={'dataset':'inventory','title':'库存','status':'available','rows':[{'country':'菲律宾','currency':'','sku_count':2,'on_hand':5,'available':4,'unmapped_count':1}],'data_range':'today','filters':{}}
    with patch('apps.integrations.feishu_reports._query',return_value={}), patch('apps.integrations.feishu_reports._section',return_value=section), patch('apps.integrations.feishu_reports._summary',return_value='在库5件'), patch('apps.integrations.feishu_inventory_requirements.inventory_requirements',return_value={'unmapped_item_rows':1}):
        report=build_report({'config':{'report_type':'inventory','format':'chart','inventory_risk_mode':True}},user)
    assert not report.get('suppress_delivery',False)
    card=report_chart_card(report,lambda path:path)
    assert 'on_hand' not in str(card)
    assert '5' in str(card) and '不阻断展示' in str(card)

@pytest.mark.django_db
def test_unmapped_internal_sku_keeps_sales_gmv_and_units():
    from apps.commerce.models import SalesOrderItem
    from apps.integrations.feishu_sales_operations import build_operations_report
    from tests.test_sales_realtime_board import _order
    user, tenant, platform, store, run, client = _fixture('partial-sales-unmapped')
    _order(tenant, platform, store, run, 'unmapped-item', amount='123')
    SalesOrderItem.objects.filter(sales_order__store=store).update(internal_sku=None)
    report=build_operations_report(user,{'date_from':'2026-08-17','date_to':'2026-08-17'},store_ids=[store.pk])
    assert report['operations']['rows'][0]['sales_amount'] == '123'
    assert not report['suppress_delivery']

def test_operations_card_shows_provisional_roi_and_explicit_missing_reason():
    from apps.integrations.feishu_sales_operations import operations_card
    values={'currency':'PHP','sales_amount':'100','change_percent':None,'roi':'2.5','roi_delta':None,'ad_reason':'数据拉取不全，按已入库数据计算（暂估）'}
    report={'title':'日报','operations':{'filters':{'date_from':'2026-08-17','date_to':'2026-08-17','previous_from':'2026-08-16'},'currency_groups':[values],'rows':[],'has_next':False}}
    card=operations_card(report,lambda path:path)
    assert '2.50 倍' in str(card)
    assert '暂估' in str(card)
    assert '缺少可比前期ROI' in str(card)
