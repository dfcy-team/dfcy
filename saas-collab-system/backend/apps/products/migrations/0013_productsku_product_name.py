from django.db import migrations, models


def backfill_product_names(apps, schema_editor):
    """Populate independent SKU names from legacy imports, then SPU fallback."""

    ProductSKU = apps.get_model("products", "ProductSKU")
    ProductLegacyItem = apps.get_model("products", "ProductLegacyItem")

    # ProductLegacyItem has a tenant + legacy_sku_code uniqueness constraint,
    # so the last value in this dictionary is deterministic even on databases
    # that do not support a correlated UPDATE in a data migration.
    legacy_names = {
        (row["tenant_id"], row["legacy_sku_code"]): row["product_name"]
        for row in ProductLegacyItem.objects.values(
            "tenant_id", "legacy_sku_code", "product_name"
        )
    }
    for sku in ProductSKU.objects.select_related("spu").all().iterator():
        name = legacy_names.get((sku.tenant_id, sku.legacy_sku_code))
        if not name:
            name = sku.spu.product_name
        ProductSKU.objects.filter(pk=sku.pk).update(product_name=name or "")


class Migration(migrations.Migration):
    dependencies = [("products", "0012_product_volume_precision")]

    operations = [
        migrations.AddField(
            model_name="productsku",
            name="product_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.RunPython(backfill_product_names, migrations.RunPython.noop),
    ]
