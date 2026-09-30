from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0004_inventorysnapshot_latest_lookup_idx"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="inventorysnapshot",
            index=models.Index(fields=["tenant", "-snapshot_at_utc"], name="idx_inv_tenant_recent"),
        ),
    ]
