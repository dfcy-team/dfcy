from unittest.mock import patch
import pytest
from django.db import connection

from apps.sales_management.outbound_movements import replace_shipment_lines
from apps.sales_management.warehouse_order_models import OrderWarehouseLookup, WarehouseOutboundLine
from apps.sales_management.warehouse_orders import request_lookup, synchronize
from tests.test_order_warehouse_lookup import setup_order, binding, package, response
from tests.test_sales_management import client_for, create_order

pytestmark = [pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != 'mysql', reason='Requires actual MySQL collation and length enforcement')]


def shipped(document, *skus):
    return {'warehouse_order_no':document, 'status':'DELIVERED', 'shipped_at_utc':'2026-01-01T01:00:00Z',
            'items':[{'warehouse_sku':sku,'sku':sku,'quantity':'1'} for sku in skus]}


def test_actual_mysql_case_insensitive_columns_keep_exact_document_and_sku_identity(setup_order):
    order, actor, warehouse = setup_order
    with connection.cursor() as cursor:
        cursor.execute("SELECT COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='document'", [WarehouseOutboundLine._meta.db_table])
        assert cursor.fetchone()[0].endswith('_ai_ci')
    lookup, _ = OrderWarehouseLookup.objects.get_or_create(order=order, defaults={'warehouse':warehouse})
    replace_shipment_lines(lookup.pk, order.tenant_id, warehouse.pk,
        [shipped('DOC-A','SKU-A','sku-a')], site_code='PH')
    second_order = create_order(order.tenant, order.store, 'case-second')
    second, _ = OrderWarehouseLookup.objects.get_or_create(order=second_order, defaults={'warehouse':warehouse})
    replace_shipment_lines(second.pk, order.tenant_id, warehouse.pk, [shipped('doc-a','SKU-A')], site_code='PH')
    api = client_for(actor)
    url = '/api/internal/supply-chain/v2/wms-inbound-movements/'
    data = api.get(url, {'direction':'outbound'}).data['data']
    assert data['total'] == 3 and data['quantity'] == 3
    exact = api.get(url, {'direction':'outbound','warehouse_id':warehouse.pk,'document':'DOC-A'}).data['data']
    assert exact['total'] == 2
    # An exact repeated document across lookups is ambiguous; its two case-distinct
    # SKU rows are quarantined, while the other document remains readable.
    replace_shipment_lines(second.pk, order.tenant_id, warehouse.pk,
        [shipped('doc-a','SKU-A'), shipped('DOC-A','SKU-A')], site_code='PH')
    data = api.get(url, {'direction':'outbound'}).data['data']
    assert data['total'] == 1 and data['items'][0]['document'] == 'doc-a'


def test_actual_mysql_bad_projection_does_not_roll_back_original_lookup_snapshot(setup_order):
    order, actor, warehouse = setup_order
    binding(order, actor, warehouse)
    with patch('apps.sales_management.warehouse_orders.publish_lookup'):
        lookup = request_lookup(order.pk, actor, manual=True)
    invalid = package(order)
    # The established snapshot accepts this source identifier; only the new
    # relational projection has the 191-character representation boundary.
    invalid['orderNo'] = 'D' * 192
    with patch('apps.sales_management.warehouse_orders.execute_operation', return_value=response([invalid])):
        assert synchronize(lookup.pk, str(lookup.revision)) == 'matched'
    lookup.refresh_from_db()
    assert lookup.status == 'matched' and lookup.snapshot['packages']
    assert lookup.snapshot['projection_diagnostics'] == {'document_too_long':1}
    assert not WarehouseOutboundLine.objects.filter(lookup=lookup).exists()
