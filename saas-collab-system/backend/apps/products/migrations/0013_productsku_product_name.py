from django.db import migrations, models


def backfill_product_names(apps, schema_editor):
    ProductSKU = apps.get_model("products", "ProductSKU")
    ProductLegacyItem = apps.get_model("products", "ProductLegacyItem")
    legacy_names = {
        (row["tenant_id"], row["legacy_sku_code"]): row["product_name"]
        for row in ProductLegacyItem.objects.values("tenant_id", "legacy_sku_code", "product_name")
    }
    for sku in ProductSKU.objects.select_related("spu").all().iterator():
        name = legacy_names.get((sku.tenant_id, sku.legacy_sku_code)) or sku.spu.product_name or ""
        ProductSKU.objects.filter(pk=sku.pk).update(product_name=name)


class Migration(migrations.Migration):
    dependencies = [("products", "0012_product_volume_precision")]
    operations = [
        migrations.AddField(model_name="productsku", name="product_name", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.RunPython(backfill_product_names, migrations.RunPython.noop),
    ]
