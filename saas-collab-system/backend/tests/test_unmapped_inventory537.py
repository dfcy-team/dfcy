"""Real scoped database API contracts for restored warehouse source-SKU details."""
from datetime import timedelta
from django.utils import timezone
from tests.test_country_inventory_decisions import facts, clock, stock
from tests.test_supply_chain_v2_logistics import client
from tests.test_sales_management import create_scope

URL = '/api/internal/commerce/inventory/category-query/'


def test_unmapped_inventory_latest_pagination_and_unknown_quantities(facts):
    f = facts
    orphan = stock(f['tenant'], f['warehouse'], f['sku'], source='UNLINKED', suffix='537-unlinked')
    orphan.internal_sku = None
    orphan.provided_quantity_fields = ['on_hand_qty', 'available_qty']
    orphan.save()
    api = client(f['actor'])
    params = {'country_id': f['country'].pk, 'level': 'unmapped'}
    response = api.get(URL, params)
    assert response.status_code == 200, response.data
    rows = response.data['data']['results']
    assert [(r['source_sku'], r['available_qty'], r['on_hand_qty']) for r in rows] == [('UNLINKED', 40, 50)]
    assert api.get(URL, {**params, 'offset': 20}).data['data']['results'] == []
    assert api.get(URL, {**params, 'search': 'absent'}).data['data']['count'] == 0
    orphan.provided_quantity_fields = []
    orphan.save()
    row = api.get(URL, params).data['data']['results'][0]
    assert row['available_qty'] is None and row['on_hand_qty'] is None
    newer = stock(f['tenant'], f['warehouse'], f['sku'], source='UNLINKED', suffix='537-newer', hours=0)
    assert newer.snapshot_at_utc > orphan.snapshot_at_utc
    assert api.get(URL, params).data['data']['count'] == 0


def test_unmapped_inventory_rejects_foreign_warehouse_and_country(facts):
    from apps.masterdata.models import CountrySiteMaster
    f = facts
    tenant, _, _, warehouse = create_scope('foreign-537')
    country = CountrySiteMaster.objects.create(tenant=tenant, code='foreign', name='Foreign', country_code='PH')
    from apps.products.models import ProductSPU, ProductSKU
    foreign_spu = ProductSPU.objects.create(tenant=tenant, spu_code='FOREIGN', product_name='Foreign')
    foreign_sku = ProductSKU.objects.create(tenant=tenant, spu=foreign_spu, sku_code='FOREIGN')
    orphan = stock(tenant, warehouse, foreign_sku, source='FOREIGN', suffix='537-foreign')
    orphan.internal_sku = None
    orphan.save()
    api = client(f['actor'])
    params = {'country_id': f['country'].pk, 'level': 'unmapped'}
    assert api.get(URL, params).data['data']['results'] == []
    assert api.get(URL, {**params, 'warehouse_id': warehouse.pk}).status_code == 404
    assert api.get(URL, {**params, 'country_id': country.pk}).status_code == 404
