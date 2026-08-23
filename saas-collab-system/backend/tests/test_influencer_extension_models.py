from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.influencers.models import (
    ExchangeRate,
    Influencer,
    InfluencerContact,
    InfluencerProfile,
    InfluencerRestrictEvent,
    OutreachTask,
    OutreachTarget,
    SampleFulfillment,
    VideoResult,
)
from apps.influencers.serializers import InfluencerSerializer
from apps.masterdata.models import PlatformMaster, StoreMaster
from tests.factories import create_internal_user, create_tenant


pytestmark = pytest.mark.django_db


def make_influencer(tenant, code="creator-1"):
    return Influencer.objects.create(
        tenant=tenant,
        code=code,
        name=code,
        platform="tiktok",
    )


def make_store(tenant, code="store-1"):
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"platform-{code}",
        name="TikTok",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    return StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=code,
        name=code,
        country_code="PH",
        currency="PHP",
    )


def make_task(tenant, influencer, store, owner):
    return OutreachTask.objects.create(
        tenant=tenant,
        task_no=f"task-{influencer.code}",
        influencer=influencer,
        store=store,
        dispatcher=owner,
        owner=owner,
    )


def make_fulfillment(tenant, influencer, task, store, owner):
    target = OutreachTarget.objects.create(
        tenant=tenant,
        task=task,
        influencer=influencer,
    )
    return SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no=f"fulfillment-{influencer.code}",
        request_key=f"request-{influencer.code}",
        request_hash="hash",
        outreach_task=task,
        outreach_target=target,
        influencer=influencer,
        store=store,
        owner=owner,
    )


def make_video(tenant, influencer, external_id="video-1", **kwargs):
    return VideoResult.objects.create(
        tenant=tenant,
        influencer=influencer,
        content_type=VideoResult.ContentType.VIDEO,
        platform="tiktok",
        external_content_id=external_id,
        metric_date=date(2026, 8, 19),
        currency="PHP",
        **kwargs,
    )


def test_all_extension_models_can_be_created():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)
    influencer = make_influencer(tenant)
    store = make_store(tenant)

    profile = InfluencerProfile.objects.create(
        tenant=tenant,
        influencer=influencer,
        display_name="Creator One",
        historical_gmv=Decimal("100.0000"),
        fulfillment_rate=Decimal("0.9500"),
    )
    contact = InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="creator@example.test",
        created_by=user,
    )
    event = InfluencerRestrictEvent.objects.create(
        tenant=tenant,
        influencer=influencer,
        action=InfluencerRestrictEvent.Action.BLACKLIST,
        reason="policy",
        actor=user,
    )
    video = make_video(tenant, influencer, store=store)
    rate = ExchangeRate.objects.create(
        tenant=tenant,
        base_currency="USD",
        quote_currency="PHP",
        rate=Decimal("56.2500000000"),
        effective_from=date(2026, 8, 19),
        source="reference",
        created_by=user,
    )

    assert profile.pk and contact.pk and event.pk and video.pk and rate.pk
    assert {
        model._meta.db_table
        for model in (InfluencerProfile, InfluencerContact, InfluencerRestrictEvent, VideoResult, ExchangeRate)
    } == {
        "influencers_influencerprofile",
        "influencers_influencercontact",
        "influencers_influencerrestrictevent",
        "influencers_videoresult",
        "influencers_exchangerate",
    }


def test_cross_tenant_relations_are_rejected():
    tenant_one = create_tenant()
    tenant_two = create_tenant()
    user_one = create_internal_user(tenant=tenant_one)
    user_two = create_internal_user(tenant=tenant_two)
    influencer_one = make_influencer(tenant_one)
    influencer_two = make_influencer(tenant_two)
    store_two = make_store(tenant_two)

    with pytest.raises(ValidationError):
        InfluencerProfile.objects.create(tenant=tenant_one, influencer=influencer_two)
    with pytest.raises(ValidationError):
        InfluencerContact.objects.create(
            tenant=tenant_one,
            influencer=influencer_one,
            channel="email",
            value="cross@example.test",
            created_by=user_two,
        )
    with pytest.raises(ValidationError):
        InfluencerRestrictEvent.objects.create(
            tenant=tenant_one,
            influencer=influencer_one,
            action=InfluencerRestrictEvent.Action.BLACKLIST,
            reason="cross tenant actor",
            actor=user_two,
        )
    with pytest.raises(ValidationError):
        make_video(tenant_one, influencer_one, store=store_two)
    with pytest.raises(ValidationError):
        ExchangeRate.objects.create(
            tenant=tenant_one,
            base_currency="USD",
            quote_currency="PHP",
            rate=Decimal("56"),
            effective_from=date(2026, 8, 19),
            source="reference",
            created_by=user_two,
        )


def test_exchange_rate_must_be_positive():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)

    with pytest.raises(ValidationError):
        ExchangeRate.objects.create(
            tenant=tenant,
            base_currency="USD",
            quote_currency="PHP",
            rate=Decimal("0"),
            effective_from=date(2026, 8, 19),
            source="reference",
            created_by=user,
        )
    negative = ExchangeRate(
        tenant=tenant,
        base_currency="USD",
        quote_currency="PHP",
        rate=Decimal("-1"),
        effective_from=date(2026, 8, 20),
        source="reference",
        created_by=user,
    )
    with pytest.raises(IntegrityError):
        negative.save_base(raw=True)


def test_restriction_events_are_immutable_and_not_bulk_updatable():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)
    influencer = make_influencer(tenant)
    event = InfluencerRestrictEvent.objects.create(
        tenant=tenant,
        influencer=influencer,
        action=InfluencerRestrictEvent.Action.BLACKLIST,
        reason="original",
        actor=user,
    )

    event.reason = "changed"
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        InfluencerRestrictEvent.objects.filter(pk=event.pk).update(reason="changed")
    with pytest.raises(ValidationError):
        InfluencerRestrictEvent.objects.bulk_update([event], ["reason"])
    with pytest.raises(ValidationError):
        event.delete()
    with pytest.raises(ValidationError):
        InfluencerRestrictEvent.objects.filter(pk=event.pk).delete()


def test_contact_and_video_external_identity_constraints_are_unique():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)
    influencer = make_influencer(tenant)
    InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="email",
        value="same@example.test",
        created_by=user,
    )
    with pytest.raises(ValidationError):
        InfluencerContact.objects.create(
            tenant=tenant,
            influencer=influencer,
            channel="email",
            value="same@example.test",
            created_by=user,
        )

    InfluencerContact.objects.create(
        tenant=tenant,
        influencer=influencer,
        channel="whatsapp",
        value="primary-one",
        is_primary=True,
        created_by=user,
    )
    with pytest.raises(ValidationError):
        InfluencerContact.objects.create(
            tenant=tenant,
            influencer=influencer,
            channel="email",
            value="primary-two@example.test",
            is_primary=True,
            created_by=user,
        )

    make_video(tenant, influencer, external_id="same-video")
    with pytest.raises(ValidationError):
        make_video(tenant, influencer, external_id="same-video")


def test_profile_and_exchange_rate_business_keys_are_unique():
    tenant = create_tenant()
    user = create_internal_user(tenant=tenant)
    influencer = make_influencer(tenant)
    InfluencerProfile.objects.create(tenant=tenant, influencer=influencer)
    with pytest.raises(ValidationError):
        InfluencerProfile.objects.create(tenant=tenant, influencer=influencer)

    payload = {
        "tenant": tenant,
        "base_currency": "USD",
        "quote_currency": "CNY",
        "rate": Decimal("7.2"),
        "effective_from": date(2026, 8, 19),
        "source": "manual",
        "created_by": user,
    }
    ExchangeRate.objects.create(**payload)
    with pytest.raises(ValidationError):
        ExchangeRate.objects.create(**payload)


@pytest.mark.parametrize("field", ["fulfillment_rate", "content_completion_rate"])
def test_profile_rates_must_be_between_zero_and_one(field):
    tenant = create_tenant()
    influencer = make_influencer(tenant)
    with pytest.raises(ValidationError):
        InfluencerProfile.objects.create(tenant=tenant, influencer=influencer, **{field: Decimal("1.01")})


def test_video_result_requires_consistent_task_fulfillment_and_store_links():
    tenant = create_tenant()
    owner = create_internal_user(tenant=tenant)
    influencer = make_influencer(tenant)
    other_influencer = make_influencer(tenant, code="creator-2")
    store = make_store(tenant)
    other_store = make_store(tenant, code="store-2")
    task = make_task(tenant, influencer, store, owner)
    fulfillment = make_fulfillment(tenant, influencer, task, store, owner)

    valid = make_video(
        tenant,
        influencer,
        external_id="consistent-video",
        outreach_task=task,
        sample_fulfillment=fulfillment,
        store=store,
    )
    assert valid.outreach_task_id == task.pk

    with pytest.raises(ValidationError):
        make_video(
            tenant,
            other_influencer,
            external_id="wrong-influencer",
            outreach_task=task,
        )
    with pytest.raises(ValidationError):
        make_video(
            tenant,
            influencer,
            external_id="wrong-store",
            outreach_task=task,
            sample_fulfillment=fulfillment,
            store=other_store,
        )


def test_influencer_video_metrics_are_pending_until_published_results_exist():
    tenant = create_tenant()
    influencer = make_influencer(tenant, code="pending-video")

    payload = InfluencerSerializer(influencer).data

    assert payload["video_metrics"] == {
        "status": "pending_precompute",
        "views": None,
        "live_views": None,
        "orders": None,
        "gmv": None,
    }
