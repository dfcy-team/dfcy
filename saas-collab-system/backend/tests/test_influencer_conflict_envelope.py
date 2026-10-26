import pytest

from apps.common.exceptions import custom_exception_handler
from apps.influencers.views import Conflict


@pytest.mark.parametrize("detail", [
    {"version": "Fulfillment was changed by another request."},
    {"warehouse": ["仓库国家必须与店铺国家一致。"]},
])
def test_conflict_preserves_field_errors_and_status(detail):
    response = custom_exception_handler(Conflict(detail), {})
    assert response.status_code == 409
    assert response.data["code"] == "STATE_CONFLICT"
    assert response.data["data"] == detail


def test_string_conflict_remains_actionable():
    response = custom_exception_handler(Conflict("送样编号已被占用。"), {})
    assert response.status_code == 409
    assert response.data["code"] == "STATE_CONFLICT"
    assert response.data["message"] == "送样编号已被占用。"
