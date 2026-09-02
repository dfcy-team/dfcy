from io import StringIO

import pytest
from django.core.management import call_command

from apps.influencers.models import Influencer, InfluencerProfile, VideoResult
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_video_csv_import_keeps_only_latest_real_snapshot_and_replays_as_noop(tmp_path):
    tenant = Tenant.objects.create(name="Video import", code="video-import")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="video-creator",
        name="Creator",
        platform="TikTok",
        handle="creator.account",
    )
    InfluencerProfile.objects.create(
        tenant=tenant,
        influencer=influencer,
        external_influencer_id="CREATOR-1",
    )
    path = tmp_path / "videos.csv"
    header = (
        "data_time,shop_abbr,site,video_type,creator_name,creator_id,video_title,"
        "video_id,publish_time,vv,orders,gmv_video,export_time\n"
    )
    older = "2026-08-30,TK1PH,PH,video,wrong.nickname,CREATOR-1,Old,VIDEO-1,2026-08-20,10,1,20,2026-08-30T10:00:00+00:00\n"
    latest = "2026-09-01,TK1PH,PH,video,wrong.nickname,CREATOR-1,Latest,VIDEO-1,2026-08-20,25,2,40,2026-09-01T10:00:00+00:00\n"
    path.write_text(header + older + latest, encoding="utf-8")

    dry_run = StringIO()
    call_command(
        "import_video_results_csv",
        tenant_id=tenant.pk,
        file=str(path),
        stdout=dry_run,
    )
    assert "mode=dry-run" in dry_run.getvalue()
    assert "latest_rows=1" in dry_run.getvalue()
    assert VideoResult.objects.count() == 0

    first = StringIO()
    call_command(
        "import_video_results_csv",
        tenant_id=tenant.pk,
        file=str(path),
        apply=True,
        stdout=first,
    )
    result = VideoResult.objects.get()
    assert result.influencer == influencer
    assert result.views == 25
    assert result.orders == 2
    assert result.currency == "UNKNOWN"

    refresh = StringIO()
    call_command(
        "refresh_influencer_video_profiles",
        tenant_id=tenant.pk,
        apply=True,
        stdout=refresh,
    )
    profile = InfluencerProfile.objects.get(influencer=influencer)
    assert profile.average_video_views == 25
    assert profile.historical_gmv == 40
    assert profile.historical_orders == 2
    assert profile.historical_performance["historical_gmv_source"] == "video_results"
    assert profile.historical_performance["historical_gmv_currency"] == "UNKNOWN"

    second = StringIO()
    call_command(
        "import_video_results_csv",
        tenant_id=tenant.pk,
        file=str(path),
        apply=True,
        stdout=second,
    )
    assert "noop=1" in second.getvalue()
    assert VideoResult.objects.count() == 1


def test_video_profile_refresh_does_not_sum_mixed_currencies():
    tenant = Tenant.objects.create(name="Mixed video currency", code="mixed-video-currency")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="mixed-currency-creator",
        name="Mixed currency creator",
        platform="TikTok",
        handle="mixed.currency.creator",
    )
    profile = InfluencerProfile.objects.create(tenant=tenant, influencer=influencer)
    for suffix, currency, gmv in (("USD", "USD", "10"), ("PHP", "PHP", "500")):
        VideoResult.objects.create(
            tenant=tenant,
            influencer=influencer,
            content_type=VideoResult.ContentType.VIDEO,
            platform="TikTok",
            external_content_id=f"MIXED-{suffix}",
            metric_date="2026-09-01",
            views=100,
            orders=1,
            gmv=gmv,
            currency=currency,
        )

    call_command(
        "refresh_influencer_video_profiles",
        tenant_id=tenant.pk,
        apply=True,
        stdout=StringIO(),
    )

    profile.refresh_from_db()
    assert profile.historical_gmv == 0
    assert profile.historical_orders == 0
    assert profile.historical_performance["video_total_gmv"] is None
    assert profile.historical_performance["video_gmv_mixed_currency"] is True
    assert profile.historical_performance["video_gmv_by_currency"] == {
        "PHP": "500",
        "USD": "10",
    }
    assert "historical_gmv_source" not in profile.historical_performance


def test_video_csv_import_does_not_match_creator_nickname(tmp_path):
    tenant = Tenant.objects.create(name="Video isolation", code="video-isolation")
    Influencer.objects.create(
        tenant=tenant,
        code="unrelated",
        name="Display Nickname",
        platform="TikTok",
        handle="real.handle",
    )
    path = tmp_path / "videos.csv"
    path.write_text(
        "data_time,creator_name,creator_id,video_id\n"
        "2026-09-01,Display Nickname,,VIDEO-2\n",
        encoding="utf-8",
    )
    output = StringIO()
    call_command("import_video_results_csv", tenant_id=tenant.pk, file=str(path), stdout=output)
    assert "unmatched=1" in output.getvalue()
    assert VideoResult.objects.count() == 0
