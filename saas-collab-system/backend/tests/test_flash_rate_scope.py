from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone
from datetime import timedelta
from apps.flash_sales.provider import ShopeeAdapter, SharedCooldown, Deferred, Rejected
from tests.test_flash_sales import shop

pytestmark = pytest.mark.django_db

def test_shop_endpoint_cooldown_does_not_block_other_shops_or_endpoints(shop):
    _, store, _ = shop
    adapter = ShopeeAdapter(store)
    adapter._cooldown('synthetic',450,shop='11',endpoint='get_shop_flash_sale_items')
    with pytest.raises(SharedCooldown):
        adapter._pace('synthetic',shop='11',endpoint='get_shop_flash_sale_items')
    with patch('apps.flash_sales.provider.time.sleep'):
        adapter._pace('synthetic',shop='13',endpoint='get_shop_flash_sale_items')
        adapter._pace('synthetic',shop='11',endpoint='get_shop_flash_sale_list')

@pytest.mark.parametrize('code,message,app_scope,rejected',[
    ('error_rate_limit','Too many requests',False,False),
    ('error_limit','The total API call number made by your APP has reached the daily API call limit',True,False),
    ('shop_flash_sale_exceed_max_item_limit','Too many products',False,True),
    ('error_limit','Unspecified limit',False,False),
    ('error_server','Internal server error',False,False),
])
def test_error_classification_and_scope(shop,settings,code,message,app_scope,rejected):
    settings.FLASH_SALES_LIVE_ENABLED=True
    _,store,_=shop
    auth=SimpleNamespace(expires_at=timezone.now()+timedelta(days=1),platform_store_id='11',token_id='synthetic-token',
        integration_config=SimpleNamespace(network_enabled=True,status='verified',credential_id='synthetic-reference',platform_config={'partner_id':'synthetic'}))
    custody=SimpleNamespace(retrieve_secret=lambda _:'synthetic-key',retrieve_access_token=lambda _:'synthetic-token')
    response=SimpleNamespace(status_code=200,json=lambda:{'error':code,'message':message})
    with patch('apps.flash_sales.provider.authorized_store',return_value=auth),patch('apps.flash_sales.provider.get_custody_backend',return_value=custody),patch('apps.flash_sales.provider.get_runtime_platform_config',return_value={'api_host':'https://partner.shopeemobile.com'}),patch('apps.flash_sales.provider.PlatformHttpClient.request',return_value=response):
        with pytest.raises(Rejected if rejected else Deferred):
            ShopeeAdapter(store).call('get_shop_flash_sale_items')
    adapter=ShopeeAdapter(store)
    with patch('apps.flash_sales.provider.time.sleep'):
        if app_scope:
            with pytest.raises(SharedCooldown):adapter._pace('synthetic',shop='13',endpoint='get_shop_flash_sale_list')
        else:
            adapter._pace('synthetic',shop='13',endpoint='get_shop_flash_sale_items')

def test_transport_preserves_retry_after_without_forwarding_other_headers(monkeypatch):
    from apps.integrations import developer_transport as transport
    response=SimpleNamespace(status=429,read=lambda size:b'{}',getheader=lambda name: '450' if name.lower()=='retry-after' else 'must-not-forward')
    class Connection:
        def __init__(self,*args,**kwargs):self.sock=SimpleNamespace(settimeout=lambda _:None)
        def request(self,*args,**kwargs):pass
        def getresponse(self):return response
        def close(self):pass
    monkeypatch.setattr(transport.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('8.8.8.8',443))])
    monkeypatch.setattr(transport.http.client,'HTTPSConnection',Connection)
    result=transport.gateway_transport('GET','https://partner.shopeemobile.com/synthetic')
    assert result.headers=={'Retry-After':'450'}
