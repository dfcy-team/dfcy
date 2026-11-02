import pytest
from apps.integrations.production_settings import validate_runtime_config


def binding():
    return dict(tenant_id=1, store_code='TK1PH', region='PH', platform_store_id='123', integration_config_id=1)


def test_query_does_not_enable_refresh():
    value = validate_runtime_config({'platforms': {'tiktok': {'creator_query_bindings': [binding()]}}})
    tk = value['platforms']['tiktok']
    assert tk['creator_query_bindings'] == [binding()]
    assert not tk.get('auto_refresh_bindings')


def test_refresh_does_not_enable_query():
    value = validate_runtime_config({'platforms': {'tiktok': {'auto_refresh_bindings': [binding()]}}})
    assert not value['platforms']['tiktok'].get('creator_query_bindings')


@pytest.mark.parametrize('items', [[binding(), binding()], [{'tenant_id': 1}], [dict(binding(), tenant_id=0)]])
def test_query_binding_rejects_invalid_identity(items):
    with pytest.raises(Exception):
        validate_runtime_config({'platforms': {'tiktok': {'creator_query_bindings': items}}})


def test_query_consumer_has_no_refresh_fallback():
    import inspect
    from apps.influencers import tiktok_creator_lookup
    source = inspect.getsource(tiktok_creator_lookup)
    assert 'creator_query_bindings' in source
    assert 'auto_refresh_bindings' not in source
