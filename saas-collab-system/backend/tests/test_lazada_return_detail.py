from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.return_logistics import lazada_return_logistics


def test_lazada_refuses_wrong_order_or_return_identity():
    client = SimpleNamespace(now=lambda: NOW, _request=Mock(return_value={'code': '0', 'data': {
        'reverse_order_id': 'WRONG', 'trade_order_id': 'ORDER', 'reverseOrderLineDTOList': []}}))
    with pytest.raises(ValidationError, match='identity'):
        lazada_return_logistics(client, {'reverse_order_id': 'RETURN', 'trade_order_id': 'ORDER'})
    client._request.assert_called_once_with('/rest/order/reverse/return/detail/list', {'reverse_order_id': 'RETURN'})
