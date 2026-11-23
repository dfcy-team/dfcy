from django.db import migrations, models


def copy_spu_product_type(apps, schema_editor):
    ProductSKU = apps.get_model("products", "ProductSKU")
    ProductSPU = apps.get_model("products", "ProductSPU")
    alias = schema_editor.connection.alias
    for kind in ("standard", "bundle"):
        spu_ids = ProductSPU.objects.using(alias).filter(product_type=kind).values("pk")
        ProductSKU.objects.using(alias).filter(spu_id__in=spu_ids).update(product_type=kind)


class Migration(migrations.Migration):
    dependencies = [("products", "0029_productskualias_identity_correction_source")]

    operations = [
        migrations.AddField(
            model_name="productsku",
            name="product_type",
            field=models.CharField(choices=[("standard", "普通商品"), ("bundle", "组合商品")], default="", max_length=20),
        ),
        migrations.RunPython(copy_spu_product_type, migrations.RunPython.noop),
    ]
