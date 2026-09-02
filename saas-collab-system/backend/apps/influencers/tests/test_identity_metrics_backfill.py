from io import StringIO

import pytest
from django.core.management import call_command

from apps.influencers.models import Influencer, InfluencerProfile
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_backfill_uses_unique_numeric_id_and_profile_follower_count(tmp_path):
    tenant = Tenant.objects.create(name="Backfill", code="backfill")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="legacy-sample-demo",
        name="Demo",
        platform="tiktok",
        handle="@Demo.Creator",
    )
    profile = InfluencerProfile.objects.create(tenant=tenant, influencer=influencer)
    profiles = tmp_path / "profiles.csv"
    profiles.write_text(
        "handle,normalized_handle,creator_id,follower_count\n"
        "demo.creator,demo.creator,6886420955675034625,30494\n",
        encoding="utf-8",
    )

    call_command(
        "backfill_influencer_identity_metrics",
        tenant_id=tenant.pk,
        profiles_csv=str(profiles),
        apply=True,
        stdout=StringIO(),
    )

    influencer.refresh_from_db()
    profile.refresh_from_db()
    assert influencer.follower_count == 30494
    assert profile.external_influencer_id == "6886420955675034625"


def test_backfill_rejects_ambiguous_ids_and_does_not_overwrite_real_id(tmp_path):
    tenant = Tenant.objects.create(name="Safe backfill", code="safe-backfill")
    ambiguous = Influencer.objects.create(
        tenant=tenant, code="legacy-a", name="A", platform="tiktok", handle="creator.a"
    )
    existing = Influencer.objects.create(
        tenant=tenant, code="legacy-b", name="B", platform="tiktok", handle="creator.b"
    )
    InfluencerProfile.objects.create(tenant=tenant, influencer=ambiguous)
    existing_profile = InfluencerProfile.objects.create(
        tenant=tenant, influencer=existing, external_influencer_id="123456789"
    )
    videos = tmp_path / "videos.csv"
    videos.write_text(
        "creator_name,creator_id\ncreator.a,111\ncreator.a,222\ncreator.b,999\n",
        encoding="utf-8",
    )

    call_command(
        "backfill_influencer_identity_metrics",
        tenant_id=tenant.pk,
        videos_csv=str(videos),
        apply=True,
        stdout=StringIO(),
    )

    assert InfluencerProfile.objects.get(influencer=ambiguous).external_influencer_id == ""
    existing_profile.refresh_from_db()
    assert existing_profile.external_influencer_id == "123456789"
