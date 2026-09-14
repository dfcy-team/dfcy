from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.models import CustomUser
from apps.common.responses import paginated_data
from apps.influencers.attribution import _RateResolver
from apps.influencers.models import ExchangeRate, Influencer
from apps.influencers.serializers import (
    InfluencerPublicSerializer,
    SampleFulfillmentListSerializer,
)
from apps.tenants.models import Tenant
from apps.influencers.views import BdPerformanceView


pytestmark = pytest.mark.django_db


class _InfluencerIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = Influencer
        fields = ("id", "code")


def test_fast_pagination_skips_exact_count_query():
    tenant = Tenant.objects.create(name="Fast page tenant", code="fast-page")
    for index in range(3):
        Influencer.objects.create(
            tenant=tenant,
            code=f"creator-{index}",
            name=f"Creator {index}",
            platform="tiktok",
            handle=f"creator.{index}",
        )
    request = Request(APIRequestFactory().get("/influencers", {"include_count": "false"}))

    with CaptureQueriesContext(connection) as queries:
        payload = paginated_data(
            request,
            Influencer.objects.filter(tenant=tenant).order_by("id"),
            _InfluencerIdSerializer,
            page=1,
            page_size=2,
            include_count=False,
        )

    assert payload["count"] is None
    assert payload["count_exact"] is False
    assert payload["has_next"] is True
    assert len(payload["results"]) == 2
    assert not any("COUNT(" in query["sql"].upper() for query in queries.captured_queries)


def test_bd_performance_reuses_short_lived_tenant_cache(monkeypatch, settings):
    tenant = Tenant.objects.create(name="Performance cache tenant", code="perf-cache")
    user = CustomUser.objects.create_user(username="perf-cache-user", tenant=tenant)
    end_date = timezone.localdate() - timedelta(days=1)
    start_date = end_date - timedelta(days=6)
    calls = []

    monkeypatch.setattr(
        "apps.influencers.views.check_user_permission",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "apps.influencers.views.require_all_scope",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "apps.influencers.views.default_performance_dates",
        lambda **_kwargs: (start_date, end_date),
    )

    def fake_build(**kwargs):
        calls.append(kwargs)
        return {"rows": [], "totals": {}}

    monkeypatch.setattr("apps.influencers.views.build_bd_performance", fake_build)
    settings.INFLUENCER_BD_PERFORMANCE_CACHE_TTL_SECONDS = 30
    request = Request(APIRequestFactory().get(
        "/api/internal/influencers/bd-performance/",
        {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "currency": "CNY",
        },
    ))
    request.user = user

    first = BdPerformanceView().get(request)
    second = BdPerformanceView().get(request)

    assert first.data == second.data
    assert len(calls) == 1


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
    sample_fields = SampleFulfillmentListSerializer(
        context={"include_items": False},
    ).fields
    assert "video_matches" not in sample_fields
    assert "items" not in sample_fields
    assert "item_preview" in sample_fields


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
