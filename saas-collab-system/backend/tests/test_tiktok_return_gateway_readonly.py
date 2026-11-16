from types import SimpleNamespace

import pytest

from apps.integrations.developer_transport import is_verified_readonly


@pytest.mark.parametrize('path,method,platform,auth_mode,expected', [
    ('/return_refund/202309/returns/search', 'POST', 'tiktok', 'tiktok_shop', True),
    ('/return_refund/202309/returns/search', 'PUT', 'tiktok', 'tiktok_shop', False),
    ('/return_refund/202309/returns/search', 'POST', 'shopee', 'tiktok_shop', False),
    ('/return_refund/202309/returns/search', 'POST', 'tiktok', 'bearer', False),
    ('/return_refund/202309/returns/search/', 'POST', 'tiktok', 'tiktok_shop', False),
    ('/return_refund/202309/returns/approve', 'POST', 'tiktok', 'tiktok_shop', False),
])
def test_return_search_is_an_exact_readonly_exception(path, method, platform, auth_mode, expected):
    endpoint = SimpleNamespace(relative_path=path, method=method, auth_mode=auth_mode,
                               connection=SimpleNamespace(platform=platform))
    assert is_verified_readonly(endpoint) is expected
