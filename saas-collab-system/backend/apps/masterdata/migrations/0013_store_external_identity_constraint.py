import hashlib
from collections import defaultdict

from django.db import migrations, models


def fail_on_legacy_external_store_duplicates(apps, schema_editor):
    """Stop deployment when existing archives claim one platform identity twice.

    This is deliberately a read-only preflight.  It does not pick a winner,
    rewrite an archive, or merge records; operations must resolve the
    duplicate before the database constraint is installed.
    """

    StoreMaster = apps.get_model("masterdata", "StoreMaster")
    groups = defaultdict(list)
    for row in StoreMaster.objects.exclude(external_store_id="").select_related("platform").iterator():
        external_id = str(row.external_store_id or "").strip()
        if not external_id:
            continue
        key = (
            row.tenant_id,
            str(row.platform.platform_type or "").strip().lower(),
            str(row.country_code or "").strip().upper(),
            external_id,
        )
        groups[key].append(row.id)
    duplicates = [(key, ids) for key, ids in groups.items() if len(ids) > 1]
    if duplicates:
        summary = "; ".join(
            f"tenant={key[0]},platform={key[1]},region={key[2] or '<blank>'},"
            f"external_id_digest={hashlib.sha256(key[3].encode('utf-8')).hexdigest()[:12]},rows={ids[:5]}"
            for key, ids in duplicates[:10]
        )
        raise RuntimeError(
            "Store external identity preflight failed: "
            f"{len(duplicates)} duplicate group(s) require manual resolution before migration. "
            f"Sample (non-secret ids only): {summary}"
        )


def backfill_external_store_identity_keys(apps, schema_editor):
    StoreMaster = apps.get_model("masterdata", "StoreMaster")
    for row in StoreMaster.objects.select_related("platform").all().iterator():
        external_id = str(row.external_store_id or "").strip()
        if external_id:
            canonical = (
                f"{str(row.platform.platform_type or '').strip().lower()}"
                f":{str(row.country_code or '').strip().upper()}:{external_id}"
            )
            row.external_store_identity_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        else:
            row.external_store_identity_key = None
        row.save(update_fields=["external_store_identity_key"])


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0012_reconcile_platform_catalog_choices")]

    operations = [
        migrations.RunPython(fail_on_legacy_external_store_duplicates, migrations.RunPython.noop),
        migrations.AddField(
            model_name="storemaster",
            name="external_store_identity_key",
            field=models.CharField(blank=True, default=None, max_length=64, null=True),
        ),
        migrations.RunPython(backfill_external_store_identity_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="storemaster",
            constraint=models.UniqueConstraint(
                fields=("tenant", "external_store_identity_key"),
                name="uniq_store_external_identity",
            ),
        ),
    ]
