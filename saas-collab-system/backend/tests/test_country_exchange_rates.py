import io
import json
from decimal import Decimal

import pytest

from apps.masterdata.exchange_rates import fetch_cny_rates, refresh_country_exchange_rates
from apps.masterdata.models import CountrySiteMaster
from tests.test_sales_management import create_scope


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def payload(values):
    return Response(json.dumps({"date": "2026-09-17", "cny": values}).encode())


def test_fetch_uses_fallback_and_preserves_rate_direction():
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise OSError("primary unavailable")
        return payload({"php": 9.35, "thb": 4.98})

    result = fetch_cny_rates(opener=opener)

    assert result["source"] == "cloudflare"
    assert result["rates"]["PHP"] == Decimal("9.35")
    assert result["rates"]["CNY"] == Decimal("1")
    assert len(calls) == 2


@pytest.mark.django_db
def test_refresh_updates_country_archives_without_overwriting_currency():
    tenant, _, _, _ = create_scope("exchange-rate")
    country = CountrySiteMaster.objects.create(
        tenant=tenant,
        code="country-ph",
        name="菲律宾",
        country_code="PH",
        currency="PHP",
        timezone="Asia/Manila",
    )

    result = refresh_country_exchange_rates(
        tenant=tenant,
        opener=lambda request, timeout: payload({"php": 9.35}),
    )

    country.refresh_from_db()
    assert result["updated"] == 1
    assert country.currency == "PHP"
    assert country.cny_exchange_rate == Decimal("9.3500000000")
    assert country.exchange_rate_date.isoformat() == "2026-09-17"
