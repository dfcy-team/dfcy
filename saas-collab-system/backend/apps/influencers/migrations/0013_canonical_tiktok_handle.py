import re
import unicodedata

from django.db import migrations, models


TIKTOK_USERNAME_PATTERN = re.compile(r"^[a-z0-9._]{1,255}$")


def _normalize_tiktok_username(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return value.strip().lstrip("@").strip().casefold()


def normalize_existing_tiktok_identities(apps, schema_editor):
    Influencer = apps.get_model("influencers", "Influencer")
    Snapshot = apps.get_model("influencers", "BdSampleAttributionSnapshot")

    for influencer in Influencer.objects.filter(platform__iexact="TikTok").iterator():
        normalized = _normalize_tiktok_username(influencer.handle)
        # Preserve malformed legacy values for explicit cleanup instead of
        # silently turning a recognizable account into an empty identity.
        if normalized and TIKTOK_USERNAME_PATTERN.fullmatch(normalized) and normalized != influencer.handle:
            influencer.handle = normalized
            influencer.save(update_fields=["handle"])

    for snapshot in Snapshot.objects.exclude(creator_username="").iterator():
        normalized = _normalize_tiktok_username(snapshot.creator_username)
        if not TIKTOK_USERNAME_PATTERN.fullmatch(normalized):
            normalized = ""
        if normalized != snapshot.creator_username:
            snapshot.creator_username = normalized
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
