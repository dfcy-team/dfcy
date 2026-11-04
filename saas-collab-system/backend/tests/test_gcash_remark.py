from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.sales_management.registration_services import validated_payload


@pytest.mark.parametrize("kind, fields, expected", [
    ("other", {"note": "直播达人佣金"}, "直播达人佣金"),
    ("refund", {"note": "商品破损退款"}, "商品破损退款"),
    ("other", {"note": "--"}, "--"),
    ("other", {"reason": "直播达人佣金", "note": "直播达人佣金"}, "直播达人佣金"),
    ("other", {"reason": "直播达人佣金", "note": "达人A"}, "原因：直播达人佣金；用途：达人A"),
    ("other", {"reason": "直播达人佣金", "note": "--"}, "原因：直播达人佣金；用途：--"),
    ("refund", {"reason": "商品破损退款", "note": ""}, "商品破损退款"),
])
def test_gcash_uses_one_remark(kind, fields, expected):
    payload = {"type": kind, "amount": "10", "currency": "PHP", "paid_at": "2026-10-13", **fields}
    saved = validated_payload("gcash", payload, SimpleNamespace(), object() if kind == "refund" else None)
    assert saved["note"] == expected
    assert "reason" not in saved
    assert payload == {"type": kind, "amount": "10", "currency": "PHP", "paid_at": "2026-10-13", **fields}


@pytest.mark.parametrize("kind, fields", [
    ("refund", {"note": ""}), ("other", {"note": " "}),
    ("other", {"reason": "a" * 300, "note": "b" * 300}),
])
def test_gcash_still_requires_a_bounded_remark(kind, fields):
    with pytest.raises(ValidationError):
        validated_payload("gcash", {"type": kind, "amount": "10", "currency": "PHP", "paid_at": "2026-10-13", **fields},
                          SimpleNamespace(), object() if kind == "refund" else None)
