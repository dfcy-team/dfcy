import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from apps.integrations.developer_docs import documentation_response


def test_shopee_postman_has_live_order_and_product_query_examples():
    endpoints = [
        SimpleNamespace(code='orders', name='Shopee orders', auth_mode='shopee_shop', relative_path='/api/v2/order/get_order_list'),
        SimpleNamespace(code='products', name='Shopee products', auth_mode='shopee_shop', relative_path='/api/v2/product/get_item_list'),
        SimpleNamespace(code='get_order_list', name='Other platform same code', auth_mode='bearer', relative_path='/api/v2/order/get_order_list'),
        SimpleNamespace(code='other', name='Shopee path with suffix', auth_mode='shopee_shop', relative_path='/api/v2/order/get_order_list/'),
    ]
    app = SimpleNamespace(tenant_id=1, approved_endpoint_ids=[1, 2, 3], pk=7, name='Demo')
    request = SimpleNamespace(build_absolute_uri=lambda _: 'https://example.invalid/')
    with patch('apps.integrations.developer_docs.DeveloperEndpoint.objects.filter', return_value=endpoints):
        response = documentation_response(app, request)

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        postman = json.loads(archive.read('postman.json'))
        readme = archive.read('README.md').decode()
    examples = {item['name']: json.loads(item['request']['body']['raw'])['query'] for item in postman['item']}
    order = examples['Shopee orders']
    assert order['time_range_field'] == 'create_time'
    assert 0 < order['time_from'] < order['time_to']
    assert order['time_to'] - order['time_from'] <= 86400
    assert order['page_size'] == 50
    assert examples['Shopee products'] == {'offset': 0, 'page_size': 50, 'item_status': ['NORMAL']}
    assert examples['Other platform same code'] == {}
    assert examples['Shopee path with suffix'] == {}
    assert '近 1 天 Unix 时间范围' in readme
    assert 'data.response.next_cursor' in readme and 'query.cursor' in readme
    assert 'data.response.next_offset' in readme and 'query.offset' in readme
    assert '每页均检查平台 error' in readme
