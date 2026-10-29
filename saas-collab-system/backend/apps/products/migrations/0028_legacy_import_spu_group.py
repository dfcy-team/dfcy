from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0027_productskualias")]

    operations = [
        migrations.AddField(
            model_name="productlegacyitem",
            name="import_batch_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="productlegacyitem",
            name="spu_group",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddIndex(
            model_name="productlegacyitem",
            index=models.Index(fields=["tenant", "import_batch_id", "spu_group"], name="idx_legacy_import_spu_group"),
        ),
    ]
