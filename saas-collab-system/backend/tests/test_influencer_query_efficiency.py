from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.influencers.attribution import _RateResolver
from apps.masterdata.models import CountrySiteMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_query_efficiency_migration_has_no_table_index_ddl():
    migration = import_module(
        "apps.influencers.migrations.0020_influencer_query_efficiency"
    )

    assert migration.Migration.operations == []


def test_rate_resolver_uses_one_query_for_many_dates_and_currencies():
    tenant = Tenant.objects.create(name="Rate preload tenant", code="rate-preload")
    country_rates = (
        ("PH", "PHP", "9.3500000000"),
        ("MY", "MYR", "1.6500000000"),
    )
    for country, currency, rate in country_rates:
        CountrySiteMaster.objects.create(
            tenant=tenant,
            code=f"country-{country.lower()}",
            name=country,
            country_code=country,
            currency=currency,
            cny_exchange_rate=Decimal(rate),
            exchange_rate_date=date(2026, 1, 1),
            exchange_rate_source="test",
        )

    with CaptureQueriesContext(connection) as queries:
        resolver = _RateResolver(tenant)
        for day in range(1, 29):
            resolver.convert(Decimal("100"), "PHP", "CNY", date(2026, 1, day))
            resolver.convert(Decimal("100"), "MYR", "CNY", date(2026, 1, day))

    assert len(queries) == 1


def test_rate_resolver_converts_using_country_information_rate_direction():
    tenant = Tenant.objects.create(name="Country rate tenant", code="country-rate")
    CountrySiteMaster.objects.create(
        tenant=tenant,
        code="country-ph",
        name="Philippines",
        country_code="PH",
        currency="PHP",
        cny_exchange_rate=Decimal("10"),
        exchange_rate_date=date(2026, 9, 20),
        exchange_rate_source="test-country-rate",
    )

    converted, details = _RateResolver(tenant).convert(
        Decimal("100"), "PHP", "CNY", date(2026, 6, 1)
    )

    assert converted == Decimal("10")
    assert details[0]["source"] == "country_site_master"
    assert details[0]["reference_direction"] == "1 CNY = 10.0000000000 PHP"
