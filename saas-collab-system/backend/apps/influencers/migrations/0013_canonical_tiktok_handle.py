import re

from django.db import migrations, models


TIKTOK_USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{1,255}$")


def _normalize_tiktok_username(value):
    return str(value or "").strip().lstrip("@").strip().lower()


def normalize_existing_tiktok_identities(apps, schema_editor):
    Influencer = apps.get_model("influencers", "Influencer")
    Snapshot = apps.get_model("influencers", "BdSampleAttributionSnapshot")

    for influencer in Influencer.objects.filter(platform__iexact="TikTok").iterator():
        normalized = _normalize_tiktok_username(influencer.handle)
        canonical = normalized if TIKTOK_USERNAME_PATTERN.fullmatch(normalized) else ""
        if canonical != influencer.handle:
            influencer.handle = canonical
            influencer.save(update_fields=["handle"])

    for snapshot in Snapshot.objects.select_related("influencer").iterator():
        influencer = snapshot.influencer
        canonical = ""
        if influencer and str(influencer.platform or "").lower() == "tiktok":
            normalized = _normalize_tiktok_username(influencer.handle)
            if TIKTOK_USERNAME_PATTERN.fullmatch(normalized):
                canonical = normalized
        if canonical != snapshot.creator_username:
            snapshot.creator_username = canonical
            snapshot.save(update_fields=["creator_username"])


class Migration(migrations.Migration):
    dependencies = [("influencers", "0012_sample_fulfillment_status_baseline")]

    operations = [
        migrations.AlterField(
            model_name="influencer",
            name="handle",
            field=models.CharField(
                blank=True,
                db_comment="TikTok用户名",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="bdsampleattributionsnapshot",
            name="creator_username",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(
            normalize_existing_tiktok_identities,
            migrations.RunPython.noop,
        ),
    ]
