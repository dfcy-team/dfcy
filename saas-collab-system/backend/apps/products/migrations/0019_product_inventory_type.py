from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("products", "0018_productlegacyitem_target_spu")]
    operations = [
        migrations.AddField(
            model_name=name,
            name="inventory_type",
            field=models.CharField(
                max_length=8,
                choices=[("virtual", "虚拟商品"), ("physical", "实体商品")],
                null=True,
                blank=True,
            ),
        )
        for name in ("productsku", "productlegacyitem")
    ]
