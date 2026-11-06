from datetime import datetime, timezone

import pytest
from django.db.models import QuerySet

from apps.influencers.models import SampleFulfillment
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import base_records, user_with_permissions


pytestmark = pytest.mark.django_db

URL = "/api/internal/influencers/sample-fulfillments/"


def _create_fulfillment(client, tenant, user, suffix):
    store, influencer, task = base_records(tenant, user, suffix)
    response = client.post(
        URL,
        {
            "fulfillment_no": f"DATE-{suffix}",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"date-{suffix}",
    )
    assert response.status_code == 201
    return SampleFulfillment.objects.get(fulfillment_no=f"DATE-{suffix}")


def test_created_date_filter_uses_inclusive_beijing_dates_and_preserves_tenant_scope():
    tenant = Tenant.objects.create(name="Created date tenant", code="created-date-tenant")
    user, client = user_with_permissions(tenant, "created-date-reader", "influencers.fulfillment.view", "influencers.fulfillment.manage")
    included = _create_fulfillment(client, tenant, user, "included")
    excluded = _create_fulfillment(client, tenant, user, "excluded")
    other_tenant = Tenant.objects.create(name="Other created date", code="other-created-date")
    other_user, other_client = user_with_permissions(other_tenant, "created-date-other", "influencers.fulfillment.view", "influencers.fulfillment.manage")
    foreign = _create_fulfillment(other_client, other_tenant, other_user, "foreign")

    QuerySet.update(SampleFulfillment.objects.filter(pk=included.pk), created_at=datetime(2026, 11, 5, 15, 59, tzinfo=timezone.utc))
    QuerySet.update(SampleFulfillment.objects.filter(pk=excluded.pk), created_at=datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc))
    QuerySet.update(SampleFulfillment.objects.filter(pk=foreign.pk), created_at=datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc))

    response = client.get(URL, {"created_date_from": "2026-11-05", "created_date_to": "2026-11-05"})

    assert response.status_code == 200
    assert [row["fulfillment_no"] for row in response.data["data"]["results"]] == ["DATE-included"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"created_date_from": "2026-11-05"}, ["DATE-next", "DATE-same"]),
        ({"created_date_to": "2026-11-05"}, ["DATE-same", "DATE-prior"]),
    ],
)
def test_created_date_filter_accepts_one_sided_bounds(params, expected):
    tenant = Tenant.objects.create(name="One sided", code=f"one-sided-{next(iter(params))}")
    user, client = user_with_permissions(tenant, "one-sided-reader", "influencers.fulfillment.view", "influencers.fulfillment.manage")
    rows = {suffix: _create_fulfillment(client, tenant, user, suffix) for suffix in ("prior", "same", "next")}
    for suffix, when in {
        "prior": datetime(2026, 11, 4, 15, 59, tzinfo=timezone.utc),
        "same": datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc),
        "next": datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc),
    }.items():
        QuerySet.update(SampleFulfillment.objects.filter(pk=rows[suffix].pk), created_at=when)
    rows["prior"].refresh_from_db()
    assert rows["prior"].created_at == datetime(2026, 11, 4, 15, 59, tzinfo=timezone.utc)

    response = client.get(URL, params)

    assert response.status_code == 200
    assert sorted(row["fulfillment_no"] for row in response.data["data"]["results"]) == sorted(expected)


@pytest.mark.parametrize(
    "params",
    [
        {"created_date_from": "2026-02-30"},
        {"created_date_from": "0001-01-01"},
        {"created_date_to": "2026/11/05"},
        {"created_date_to": "9999-12-31"},
        {"created_date_from": "2026-11-06", "created_date_to": "2026-11-05"},
    ],
)
def test_created_date_filter_rejects_invalid_or_reversed_bounds(params):
    tenant = Tenant.objects.create(name="Invalid dates", code=f"invalid-{len(params)}-{str(params)[:8]}")
    _, client = user_with_permissions(tenant, "invalid-date-reader", "influencers.fulfillment.view")

    response = client.get(URL, params)

    assert response.status_code == 400
