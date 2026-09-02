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
