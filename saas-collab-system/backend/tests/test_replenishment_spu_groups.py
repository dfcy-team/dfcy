from datetime import timedelta
from decimal import Decimal

import pytest

from apps.products.models import ProductSKU, ProductSPU
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import ReplenishmentCalculationJob, ReplenishmentCalculationRow
from apps.supply_chain import replenishment_jobs as jobs
from tests.test_replenishment_strategy_flow import configured
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_logistics import client

pytestmark = pytest.mark.django_db
ROWS = '/api/internal/supply-chain/v2/replenishment-jobs/{}/rows/'


def make_job(world, configured, actor, spu_rows):
    _, strategy, _ = configured
    job = ReplenishmentCalculationJob.objects.create(
        tenant=actor.tenant, requested_by=actor, country=world['country'], strategy=strategy,
        strategy_version=strategy.version, business_date=business_date(), config={},
        candidate_ids=[sku_id for group in spu_rows for sku_id, _ in group], permission_signature=jobs._scope_signature(actor),
        status='completed', total=sum(len(group) for group in spu_rows),
        processed=sum(len(group) for group in spu_rows), counts={},
        expires_at=__import__('django.utils.timezone', fromlist=['now']).now()+timedelta(days=1),
        hard_deadline=__import__('django.utils.timezone', fromlist=['now']).now()+timedelta(days=1))
    for group in spu_rows:
        for sku_id, payload in group:
            payload={**payload, 'sku_id':sku_id, 'sku_code':str(sku_id)}
            ReplenishmentCalculationRow.objects.create(job=job, sku_id=sku_id,
                sku_code=str(sku_id), legacy_sku_code='', product_name='',
                suggested_quantity=payload.get('suggested_quantity'), risk_level='normal',
                has_submitted_demand=False, payload=payload)
    return job


def test_spu_group_pages_match_filter_but_totals_include_all_children(world, configured):
    actor, _, _ = configured
    spu2 = ProductSPU.objects.create(tenant=actor.tenant, spu_code='SPU-B', legacy_spu_code='OLD-B', product_name='Beta', sales_status='on_sale')
    b1 = ProductSKU.objects.create(tenant=actor.tenant, spu=spu2, sku_code='B-1', image_url='https://safe/image.jpg')
    b2 = ProductSKU.objects.create(tenant=actor.tenant, spu=spu2, sku_code='B-2')
    a1, a2 = world['sku'], world['sku_b']
    a1.image_url='https://safe/a.jpg';a1.save(update_fields=['image_url'])
    job=make_job(world,configured,actor,[
        [(a1.pk,{'suggested_quantity':5,'business_decision':{'category':'purchase'},'formula_evidence':{'sales':{'30':{'units':4}}},'available_stock':0}),
         (a2.pk,{'suggested_quantity':0,'business_decision':{'category':'sufficient'},'formula_evidence':{'sales':{'30':{'units':None}}},'available_stock':None})],
        [(b1.pk,{'suggested_quantity':3,'business_decision':{'category':'purchase'},'formula_evidence':{'sales':{'30':{'units':2}}},'available_stock':8}),
         (b2.pk,{'suggested_quantity':None,'business_decision':{'category':'sufficient'},'formula_evidence':{'sales':{'30':{'units':0}}},'available_stock':0})],
    ])
    api=client(actor)
    response=api.get(ROWS.format(job.pk),{'group_by':'spu','quantity_filter':'purchase','limit':1,'offset':0})
    assert response.status_code==200,response.data
    data=response.data['data'];assert data['count']==2 and len(data['rows'])==1 and data['has_more']
    # Filtered SKU determines inclusion, while aggregate values cover the complete SPU.
    assert data['rows'][0]['matched_sku_count']==1
    assert data['rows'][0]['sku_count']==2
    assert data['rows'][0]['suggested_quantity']==5
    assert data['rows'][0]['sales_30']==4
    assert data['rows'][0]['available_stock']==0
    assert data['rows'][0]['sales_30']==4
    assert data['rows'][0]['available_stock']==0
    assert data['rows'][0]['spu_name']=='Widget'
    next_page=api.get(ROWS.format(job.pk),{'group_by':'spu','quantity_filter':'purchase','limit':1,'offset':1}).data['data']['rows'][0]
    assert next_page['spu_code']=='SPU-B' and next_page['image_sku_id']==b1.pk
    repeated=api.get(ROWS.format(job.pk),{'group_by':'spu','quantity_filter':'purchase','limit':1,'offset':1}).data['data']['rows'][0]
    assert repeated['image_sku_id']==next_page['image_sku_id']
    searched=api.get(ROWS.format(job.pk),{'group_by':'spu','quantity_filter':'purchase','search':'Beta'}).data['data']
    assert searched['count']==1 and searched['rows'][0]['spu_name']=='Beta'


def test_spu_detail_positive_filter_and_tenant_isolation(world, configured):
    actor, _, _=configured
    foreign_world={**world}
    from apps.tenants.models import Tenant
    from apps.masterdata.models import CountrySiteMaster
    tenant=Tenant.objects.create(name='foreign spu tenant',code='foreign-spu-tenant')
    foreign_spu=ProductSPU.objects.create(tenant=tenant,spu_code='FOREIGN',product_name='foreign')
    foreign_sku=ProductSKU.objects.create(tenant=tenant,spu=foreign_spu,sku_code='FOREIGN-SKU')
    a1,a2=world['sku'],world['sku_b']
    job=make_job(world,configured,actor,[[(a1.pk,{'suggested_quantity':4,'business_decision':{'category':'purchase'},'available_stock':None}), (a2.pk,{'suggested_quantity':0,'available_stock':0})]])
    api=client(actor)
    positive=api.get(ROWS.format(job.pk),{'group_by':'sku','spu_id':world['spu'].pk,'quantity_filter':'positive'})
    assert positive.status_code==200 and positive.data['data']['count']==1
    assert positive.data['data']['rows'][0]['sku_id']==a1.pk
    all_rows=api.get(ROWS.format(job.pk),{'group_by':'sku','spu_id':world['spu'].pk,'quantity_filter':'all'})
    assert all_rows.status_code==200 and all_rows.data['data']['count']==2
    foreign=api.get(ROWS.format(job.pk),{'group_by':'sku','spu_id':foreign_spu.pk,'quantity_filter':'all'})
    assert foreign.status_code==400
    assert all_rows.data['data']['rows'][0]['available_stock'] is None
    assert all_rows.data['data']['rows'][1]['available_stock']==0
