from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser
from apps.influencers.attribution import _RateResolver
from apps.influencers.models import ExchangeRate, Influencer
from apps.influencers.serializers import (
    InfluencerPublicSerializer,
    SampleFulfillmentListSerializer,
)
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_collection_serializers_exclude_relation_payloads():
    tenant = Tenant.objects.create(name="List payload tenant", code="list-payload")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="compact-creator",
        name="Compact Creator",
        platform="tiktok",
        handle="compact.creator",
    )
    influencer._is_blacklisted = False

    influencer_payload = InfluencerPublicSerializer(
        influencer,
        context={"include_relations": False},
    ).data

    assert "contacts" not in influencer_payload
    assert "blacklist_history" not in influencer_payload
    assert "video_matches" not in SampleFulfillmentListSerializer().fields


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
