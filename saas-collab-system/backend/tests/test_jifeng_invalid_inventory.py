from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import JifengWmsReadonlyClient


def test_jifeng_inventory_rejects_mixed_valid_and_invalid_rows():
    client = JifengWmsReadonlyClient(
        SimpleNamespace(platform="jifeng_wms", platform_config={}),
        SimpleNamespace(external_warehouse_code="TEST-WAREHOUSE"),
        custody=object(),
    )
    client._signed_post = Mock(return_value={
        "code": 0,
        "data": {"page": {"rows": [{"sku": "SKU-1"}, None], "totalPage": 1}},
    })

    with pytest.raises(ValidationError, match="库存响应包含无效记录"):
        client.fetch_inventory(None, {"page_size": 10})
