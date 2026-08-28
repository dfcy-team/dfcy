import hashlib
import unicodedata

from django.db import migrations, models


def normalize_tiktok_username(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return value.strip().lstrip("@").strip().casefold()


def digest_tiktok_username(value):
    canonical = normalize_tiktok_username(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""


def populate_canonical_handles(apps, schema_editor):
    Influencer = apps.get_model("influencers", "Influencer")
    for influencer in Influencer.objects.all().iterator(chunk_size=1000):
        canonical = (
            normalize_tiktok_username(influencer.handle)
            if str(influencer.platform or "").casefold() == "tiktok"
            else ""
        )
        digest = digest_tiktok_username(canonical)
        if influencer.canonical_handle != canonical or influencer.canonical_handle_digest != digest:
            influencer.canonical_handle = canonical
            influencer.canonical_handle_digest = digest
            influencer.save(update_fields=["canonical_handle", "canonical_handle_digest"])


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
        migrations.AddField(
            model_name="influencer",
            name="canonical_handle_digest",
            field=models.CharField(
                blank=True,
                db_comment="标准化TikTok用户名SHA-256摘要",
                default="",
                editable=False,
                max_length=64,
            ),
        ),
        migrations.AddIndex(
            model_name="influencer",
            index=models.Index(
                fields=["tenant", "platform", "canonical_handle_digest"],
                name="idx_inf_tenant_platform_digest",
            ),
        ),
        migrations.RunPython(populate_canonical_handles, migrations.RunPython.noop),
    ]
