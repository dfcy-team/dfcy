"""Independent-review regressions using real scoped queries and synthetic data."""
import pytest
from django.core.cache import cache

from apps.products.models import ProductCategory, ProductSKU
from tests.test_country_inventory_decisions import clock, facts, stock
from tests.test_sales_management import client_for

pytestmark = pytest.mark.django_db
URL = '/api/internal/commerce/inventory/category-query/'


def test_uncategorized_and_positive_category_selection_intersect_to_empty(facts):
    f=facts
    category=ProductCategory.objects.create(tenant=f['tenant'],level=1,code='9',name='Selected')
    assert f['spu'].category_node_id is None
    response=client_for(f['actor']).get(URL,{'country_id':f['country'].pk,'level':'sku',
                                             'category_id':0,'category_ids':str(category.pk)})
    assert response.status_code==200,response.data
    assert response.data['data']['count']==0
    assert response.data['data']['results']==[]


@pytest.mark.parametrize('level',['stores','warehouses'])
def test_detail_envelope_preserves_scoped_summary_and_coverage(facts,level):
    f=facts
    response=client_for(f['actor']).get(URL,{'country_id':f['country'].pk,'level':level,'sku_id':f['sku'].pk})
    assert response.status_code==200,response.data
    summary=response.data['data']['summary']
    assert {'sku_count','spu_count','available','sales','stock_coverage','sales_coverage'} <= summary.keys()
    assert summary['sku_count']==1 and summary['spu_count']==1
    assert summary['available']==40 and summary['stock_coverage']==1


def test_unconfirmed_onhand_does_not_invent_unlisted_stock_or_sales_zero(facts,monkeypatch):
    f=facts
    sku=ProductSKU.objects.create(tenant=f['tenant'],spu=f['spu'],sku_code='UNVERIFIED-ONHAND')
    stock(f['tenant'],f['warehouse'],sku,suffix='unverified-onhand',quantity=5,provided=False)
    monkeypatch.setattr('apps.sales_management.category_inventory.sales_facts',lambda *a,**kw:[])
    cache.clear()
    response=client_for(f['actor']).get(URL,{'country_id':f['country'].pk,'level':'sku'})
    assert response.status_code==200,response.data
    row=next(row for row in response.data['data']['results'] if row['id']==sku.pk)
    assert row['available'] is None
    assert row['sales'] is None
    assert not row.get('stock_sales_reason')
    assert row.get('unlisted_stock_sku_count',0)==0
