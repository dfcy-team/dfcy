import pytest
from django.db.models import QuerySet
from django.utils import timezone

from apps.influencers.models import SampleFulfillment
from apps.tenants.models import Tenant
from tests.test_sample_fulfillment_created_dates import _create_fulfillment
from tests.test_influencer_fulfillment import user_with_permissions

pytestmark = pytest.mark.django_db


def test_duplicate_warning_matches_the_same_creator_across_stores_and_products():
    tenant = Tenant.objects.create(name="Duplicate sample tenant", code="duplicate-sample-tenant")
    user, client = user_with_permissions(tenant, "duplicate-sample-reader", "influencers.fulfillment.view", "influencers.fulfillment.manage")
    sample = _create_fulfillment(client, tenant, user, "duplicate-match")
    other = _create_fulfillment(client, tenant, user, "duplicate-other")
    QuerySet.update(SampleFulfillment.objects.filter(pk=other.pk), status="shipped", external_product_id="123")
    url = "/api/internal/influencers/resolve/"
    params = {"duplicate_influencer": sample.influencer_id}
    allowed = {"pending", "shipped", "delivered", "overdue", "blacklisted"}
    for state in SampleFulfillment.Status.values:
        QuerySet.update(SampleFulfillment.objects.filter(pk=sample.pk), status=state, external_product_id="456")
        response = client.get(url, params)
        assert response.status_code == 200
        expected = [{"fulfillment_no": sample.fulfillment_no, "status": state}] if state in allowed else []
        assert response.data["data"]["records"] == expected

    QuerySet.update(SampleFulfillment.objects.filter(pk=other.pk), influencer_id=sample.influencer_id)
    assert sample.store_id != other.store_id
    QuerySet.update(SampleFulfillment.objects.filter(pk=sample.pk), status="shipped")
    assert {r["fulfillment_no"] for r in client.get(url, params).data["data"]["records"]} == {sample.fulfillment_no, other.fulfillment_no}
    assert client.get(url, {"duplicate_influencer": other.influencer_id}).data["data"]["records"] == []
    assert client.get(url, {"duplicate_influencer": ""}).status_code == 400
    QuerySet.update(SampleFulfillment.objects.filter(pk=sample.pk), is_deleted=True, deleted_at=timezone.now(), deleted_by_id=user.pk)
    assert client.get(url, params).data["data"]["records"] == [{"fulfillment_no": other.fulfillment_no, "status": "shipped"}]
