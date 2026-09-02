from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("products", "0006_productattribute")]
    operations = [
        migrations.AddField(model_name="productspu", name="legacy_spu_code", field=models.CharField(blank=True, db_index=True, max_length=120)),
        migrations.AddField(model_name="productsku", name="legacy_sku_code", field=models.CharField(blank=True, db_index=True, max_length=160)),
        migrations.CreateModel(name="ProductLegacyItem", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("legacy_spu_code", models.CharField(blank=True, max_length=120)), ("legacy_sku_code", models.CharField(max_length=160)),
            ("product_name", models.CharField(max_length=200)), ("attribute_code", models.CharField(blank=True, default="0", max_length=1)),
            ("color_code", models.CharField(blank=True, max_length=40)), ("specification", models.CharField(blank=True, max_length=120)),
            ("status", models.CharField(choices=[("pending", "Pending"), ("generated", "Generated"), ("error", "Error")], default="pending", max_length=20)),
            ("error_message", models.CharField(blank=True, max_length=500)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("category_node", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="products.productcategory")),
            ("generated_sku", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="products.productsku")),
            ("generated_spu", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="products.productspu")),
            ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="legacy_product_items", to="tenants.tenant")),
        ], options={"ordering": ["-created_at", "id"]}),
        migrations.AddConstraint(model_name="productlegacyitem", constraint=models.UniqueConstraint(fields=("tenant", "legacy_sku_code"), name="uniq_legacy_sku_per_tenant")),
    ]
