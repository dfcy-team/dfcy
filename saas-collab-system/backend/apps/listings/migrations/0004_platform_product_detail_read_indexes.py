from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("listings", "0003_platformproductdetail")]
    operations = [
        migrations.AddIndex(
            model_name="platformproductdetail",
            index=models.Index(fields=["tenant", "updated_at", "id"], name="idx_platform_product_updated"),
        ),
        migrations.AddIndex(
            model_name="platformproductdetail",
            index=models.Index(fields=["tenant", "platform", "updated_at", "id"], name="idx_platform_product_platform"),
        ),
        migrations.AddIndex(
            model_name="platformproductdetail",
            index=models.Index(fields=["tenant", "store", "updated_at", "id"], name="idx_platform_product_store_upd"),
        ),
    ]
