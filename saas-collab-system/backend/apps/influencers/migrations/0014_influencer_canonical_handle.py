import unicodedata

from django.db import migrations, models


def normalize_tiktok_username(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return value.strip().lstrip("@").strip().casefold()


def populate_canonical_handles(apps, schema_editor):
    Influencer = apps.get_model("influencers", "Influencer")
    for influencer in Influencer.objects.all().iterator(chunk_size=1000):
        canonical = (
            normalize_tiktok_username(influencer.handle)
            if str(influencer.platform or "").casefold() == "tiktok"
            else ""
        )
        if influencer.canonical_handle != canonical:
            influencer.canonical_handle = canonical
            influencer.save(update_fields=["canonical_handle"])


class Migration(migrations.Migration):
    dependencies = [("influencers", "0013_canonical_tiktok_handle")]

    operations = [
        migrations.AddField(
            model_name="influencer",
            name="canonical_handle",
            field=models.CharField(
                blank=True,
                db_comment="标准化TikTok用户名",
                db_index=True,
                default="",
                editable=False,
                max_length=255,
            ),
        ),
        migrations.RunPython(populate_canonical_handles, migrations.RunPython.noop),
    ]
