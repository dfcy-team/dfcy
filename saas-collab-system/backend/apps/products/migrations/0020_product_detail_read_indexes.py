from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0019_product_inventory_type")]
    operations = [
        migrations.AddIndex(
            model_name="productsku",
            index=models.Index(fields=["tenant", "is_active", "updated_at", "id"], name="idx_sku_tenant_active_updated"),
        ),
        migrations.AddIndex(
            model_name="productsku",
            index=models.Index(fields=["tenant", "updated_at", "id"], name="idx_sku_tenant_updated"),
        ),
        migrations.AddIndex(
            model_name="productlegacyitem",
            index=models.Index(fields=["tenant", "updated_at", "id"], name="idx_legacy_tenant_updated"),
        ),
        migrations.AddIndex(
            model_name="productlegacyitem",
            index=models.Index(fields=["tenant", "generated_sku"], name="idx_legacy_tenant_generated"),
        ),
    ]
