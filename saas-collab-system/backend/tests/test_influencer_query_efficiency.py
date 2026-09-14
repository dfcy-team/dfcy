from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.influencers.attribution import _RateResolver
from apps.influencers.models import ExchangeRate
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_query_efficiency_migration_has_no_table_index_ddl():
    migration = import_module(
        "apps.influencers.migrations.0020_influencer_query_efficiency"
    )

    assert migration.Migration.operations == []


def test_rate_resolver_uses_one_query_for_many_dates_and_currencies():
    tenant = Tenant.objects.create(name="Rate preload tenant", code="rate-preload")
    user = CustomUser.objects.create_user(username="rate-owner", tenant=tenant)
    for currency, rate in (("PHP", "0.1200000000"), ("MYR", "1.6500000000")):
        ExchangeRate.objects.create(
            tenant=tenant,
            base_currency=currency,
            quote_currency="CNY",
            rate=Decimal(rate),
            effective_from=date(2026, 1, 1),
            source="test",
            created_by=user,
        )

    with CaptureQueriesContext(connection) as queries:
        resolver = _RateResolver(tenant)
        for day in range(1, 29):
            resolver.convert(Decimal("100"), "PHP", "CNY", date(2026, 1, day))
            resolver.convert(Decimal("100"), "MYR", "CNY", date(2026, 1, day))

    assert len(queries) == 1
