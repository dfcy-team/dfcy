from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.sales_management.registration_services import validated_payload


@pytest.mark.parametrize("value, expected", [
    ("2026-09-28", "2026-09-28"),
    ("2024-02-29", "2024-02-29"),
    ("2026-09-28T00:00:00+08:00", "2026-09-28"),
    ("2026-09-27T18:00:00+00:00", "2026-09-28"),
])
def test_gcash_payment_date_is_normalized(value, expected):
    payload = {"type": "other", "note": "--", "reason": "退款登记",
               "amount": "10", "currency": "PHP", "paid_at": value}
    assert validated_payload("gcash", payload, SimpleNamespace(), None)["paid_at"] == expected
    assert payload["paid_at"] == value


@pytest.mark.parametrize("value", ["", None, 20260928, "2026-9-28", "2026/09/28",
                                       "2026-02-29", "2026-09-28T00:00:00"])
def test_gcash_rejects_invalid_payment_date(value):
    payload = {"type": "other", "note": "--", "reason": "退款登记",
               "amount": "10", "currency": "PHP", "paid_at": value}
    with pytest.raises(ValidationError):
        validated_payload("gcash", payload, SimpleNamespace(), None)
