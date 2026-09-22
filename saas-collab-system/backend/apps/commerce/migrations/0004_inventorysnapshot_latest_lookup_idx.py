from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0003_salesorderbundlesnapshot_bundle_version_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="inventorysnapshot",
            index=models.Index(
                fields=["tenant", "site_code", "warehouse", "source_sku", "-snapshot_at_utc", "-id"],
                name="idx_inv_latest_lookup",
            ),
        ),
    ]
