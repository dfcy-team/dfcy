from types import SimpleNamespace

import pytest

from apps.influencers.models import OutreachTask, SampleFulfillment
from apps.influencers.business_numbers import next_number
from apps.influencers.services import (
    _generate_outreach_task_no,
    _generate_sample_fulfillment_no,
    create_outreach_task,
    create_sample_fulfillment,
    soft_delete_outreach_task,
    soft_delete_sample_fulfillment,
)
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import base_records, user_with_permissions


pytestmark = pytest.mark.django_db


@pytest.fixture
def r():
    tenant = Tenant.objects.create(name="Numbering example", code="numbering-example")
    user, _ = user_with_permissions(tenant, "numbering-example", "influencers.outreach.manage", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "numbering-example")
    return SimpleNamespace(tenant=tenant, user=user, store=store, influencer=influencer, task=task)


def seed_sample(r, number, *, pk=None):
    return SampleFulfillment.objects.create(
        tenant=r.tenant, pk=pk, fulfillment_no=number,
        type_no=None if number.startswith("YPDD") else number,
        request_key=f"synthetic-{number}", request_hash="0" * 64,
        influencer=r.influencer, store=r.store, owner=r.user, link_type="direct",
    )


def create_sample(r, link_type, key):
    data = {"influencer": r.influencer, "store": r.store,
            "external_product_id": "EXAMPLE-PRODUCT", "link_type": link_type}
    if link_type == "DRJL":
        data["outreach_task"] = r.task
        data["external_product_id"] = r.task.external_product_id
    return create_sample_fulfillment(user=r.user, request_key=key, validated_data=data, item_payloads=[])


def test_task_number_continues_business_suffix_not_database_id(r):
    OutreachTask.objects.create(
        id=480364, tenant=r.tenant, task_no="DRJL0279", store=r.store,
        influencer=r.influencer, owner=r.user, dispatcher=r.user,
    )
    assert _generate_outreach_task_no(r.tenant) == "DRJL0280"
    task = create_outreach_task(user=r.user, validated_data={"store": r.store, "owner": r.user})
    assert task.pk >= 480365
    assert task.task_no == "DRJL0280"


def test_each_sample_type_continues_its_own_sequence_ignoring_large_ids_and_legacy_numbers(r):
    history = seed_sample(r, "YPDD10987", pk=480364)
    seed_sample(r, "DRJL0004")
    seed_sample(r, "YYJL0001")
    assert _generate_sample_fulfillment_no(r.tenant, "DRJL") == "YPDD10988"
    expected = (("DRJL", "DRJL0005"), ("YYJL", "YYJL0002"), ("PKDJ", "PKDJ0001"),
                ("ZBDR", "ZBDR0001"), ("TKOne", "TKOne0001"), ("direct", "direct0001"))
    for index, (link_type, number) in enumerate(expected):
        sample, created = create_sample(r, link_type, f"number-{link_type}")
        assert created
        assert sample.type_no == number
        assert sample.fulfillment_no == f"YPDD{10988 + index}"
        assert sample.link_type == link_type
    history.refresh_from_db()
    assert history.fulfillment_no == "YPDD10987"


def test_deleted_samples_and_tasks_keep_their_numbers_reserved(r):
    sample, _ = create_sample(r, "YYJL", "deleted-reservation")
    assert sample.fulfillment_no == "YPDD00001"
    assert sample.type_no == "YYJL0001"
    soft_delete_sample_fulfillment(user=r.user, fulfillment=sample, expected_version=sample.version)
    assert _generate_sample_fulfillment_no(r.tenant, "YYJL") == "YPDD00002"
    assert next_number(r.tenant, "type", "YYJL") == "YYJL0002"
    assert next_number(r.tenant, "type", "PKDJ") == "PKDJ0001"
    task = create_outreach_task(user=r.user, validated_data={"store": r.store, "owner": r.user})
    soft_delete_outreach_task(user=r.user, task=task, expected_version=task.version)
    assert _generate_outreach_task_no(r.tenant) == "DRJL0003"


def test_sample_number_uses_numeric_max_not_row_order_or_lexical_order(r):
    seed_sample(r, "DRJL9999")
    seed_sample(r, "DRJL10000")
    seed_sample(r, "DRJL0007")
    seed_sample(r, "DRJL999999-invalid")
    assert next_number(r.tenant, "type", "DRJL") == "DRJL10001"
    assert next_number(r.tenant, "type", "YYJL") == "YYJL0001"


def test_sample_numbering_is_tenant_scoped(r):
    seed_sample(r, "DRJL0279")
    other_tenant = Tenant.objects.create(name="Other numbering example", code="other-numbering-example")
    other_user, _ = user_with_permissions(other_tenant, "other-numbering-example", "influencers.fulfillment.manage")
    store, influencer, task = base_records(other_tenant, other_user, "other-numbering-example")
    other = SimpleNamespace(tenant=other_tenant, user=other_user, store=store, influencer=influencer, task=task)
    seed_sample(other, "DRJL9999")
    assert next_number(r.tenant, "type", "DRJL") == "DRJL0280"
    assert next_number(other_tenant, "type", "DRJL") == "DRJL10000"


def test_idempotent_retry_does_not_consume_or_change_a_number(r):
    seed_sample(r, "YYJL0007")
    sample, created = create_sample(r, "YYJL", "retry-number")
    repeated, created_again = create_sample(r, "YYJL", "retry-number")
    assert created and not created_again
    assert sample.pk == repeated.pk
    assert sample.fulfillment_no == repeated.fulfillment_no == "YPDD00001"
    assert sample.type_no == repeated.type_no == "YYJL0008"
    assert next_number(r.tenant, "type", "YYJL") == "YYJL0009"
    assert next_number(r.tenant, "type", "DRJL") == "DRJL0001"


def test_controlled_callers_can_still_preserve_an_explicit_historical_number(r):
    sample, created = create_sample_fulfillment(
        user=r.user, request_key="explicit-historical-number",
        validated_data={"influencer": r.influencer, "store": r.store,
                        "link_type": "direct", "fulfillment_no": "LEGACY-IMPORT-7"},
        item_payloads=[],
    )
    assert created and sample.fulfillment_no == "LEGACY-IMPORT-7"
    assert _generate_sample_fulfillment_no(r.tenant, "DRJL") == "YPDD00001"
