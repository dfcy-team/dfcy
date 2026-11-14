import json
from copy import deepcopy
from datetime import date

import pytest

from apps.finance.summary_recent import recent_scope, preserve_history


@pytest.mark.parametrize('today,start', [(date(2026,11,14),'2026-10-01'), (date(2027,1,1),'2026-12-01'), (date(2028,3,1),'2028-02-01')])
def test_recent_calendar_months(monkeypatch,today,start):
    monkeypatch.setattr('apps.finance.summary_recent.timezone.localdate',lambda **kwargs:today)
    assert recent_scope([1]) == {'from':start,'to':str(today),'stores':[1]}


def test_recent_refresh_preserves_history_and_removes_cancelled_recent_rows():
    historic={'source_id':'old','date':'2026-09-30','amount':'-10','store_id':1,'external_order_id':'A'}
    stale={'source_id':'cancelled-fee','date':'2026-10-01','amount':'-20'}
    current={'source_id':'new-return','date':'2026-11-01','amount':'5'}
    old={'facts':[historic,stale], 'raw_flows':[historic,stale], 'cost_flows':[historic,stale],
         'shares':{'order':[historic,stale]},'rates':{'monthly':{'2026-09|x':'old','2026-10|x':'stale'},'historical':{}},
         'order_dates':{'1|A':{'date':'2026-09-20'}}}
    sku={'orders':{'1|A':[{'quantity':1}]},'exchanges':{}}
    products={'rows':[],'products':[]}
    recharge={'transactions':[historic,stale],'actualSpend':None}
    cycles={'shops':{}}
    snapshot={'database':old,'raw':[historic,stale],'shopee_income':[], 'lazada_saas':{'sku_members':[]}}
    template='<script id="snapshot">'+json.dumps(snapshot)+'</script>'
    for name,value in [('HTML2_SKU_ORDER_SALES',sku),('HTML2_PRODUCT_LINK_DATA',products),('HTML2_RECHARGE_DATA',recharge),('HTML2_LAZADA_CYCLES',cycles)]:
        template+='<script>globalThis.'+name+'='+json.dumps(value)+';</script>'
    fresh={**deepcopy(old),'raw':[current],'shopee_income':[],'sku_members':[], 'products':products,
           'sku_sales':{'orders':{'1|A':[{'quantity':99}]},'exchanges':{}},
           'recharge':{'transactions':[],'actualSpend':None},'cycles':cycles,'source_counts':{}}
    for key in ('facts','raw_flows','cost_flows'):
        fresh[key]=[current, {**historic, 'date':'2026-11-02','amount':'-99'}]
    fresh['shares']={'order':[current]}
    fresh['rates']['monthly']={'2026-09|x':'changed','2026-11|x':'new'}
    fresh['order_dates']={'1|A':{'date':'2026-11-20'}}
    original=deepcopy(fresh)
    merged=preserve_history(template,fresh,'2026-10-01')
    for key in ('facts','raw_flows','cost_flows','raw'):assert merged[key]==[historic,current]
    assert merged['rates']['monthly']=={'2026-09|x':'old','2026-11|x':'new'}
    assert merged['order_dates']['1|A']==old['order_dates']['1|A']
    assert merged['sku_sales']==sku
    assert merged['recharge']['transactions']==[historic]
    assert merged['cycles']['history']['2026-09']==cycles['shops']
    assert fresh==original
