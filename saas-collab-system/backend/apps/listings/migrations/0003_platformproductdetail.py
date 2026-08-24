import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("listings", "0002_listingpublicationjob_confirmed_production_and_more"),
        ("masterdata", "0008_merge_country_and_store_branches"),
        ("products", "0013_productsku_product_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformProductDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("platform_product_id", models.CharField(blank=True, default="", max_length=160)),
                ("platform_variant_id", models.CharField(max_length=160)),
                ("platform_sku", models.CharField(blank=True, default="", max_length=160)),
                ("source_old_sku_code", models.CharField(blank=True, default="", max_length=160)),
                ("title", models.CharField(blank=True, default="", max_length=300)),
                ("variant", models.CharField(blank=True, default="", max_length=300)),
                ("category_l1", models.CharField(blank=True, default="", max_length=200)),
                ("category_l2", models.CharField(blank=True, default="", max_length=200)),
                ("category_l3", models.CharField(blank=True, default="", max_length=200)),
                ("sku_prefix", models.CharField(blank=True, default="", max_length=120)),
                ("shop_abbr", models.CharField(blank=True, default="", max_length=120)),
                ("sales_status", models.CharField(blank=True, default="", max_length=80)),
                ("owner", models.CharField(blank=True, default="", max_length=120)),
                ("leader", models.CharField(blank=True, default="", max_length=120)),
                ("platform_created_at", models.DateTimeField(blank=True, null=True)),
                ("platform_updated_at", models.DateTimeField(blank=True, null=True)),
                ("source", models.CharField(blank=True, default="manual", max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("internal_sku", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="platform_product_details", to="products.productsku")),
                ("platform", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="product_details", to="masterdata.platformmaster")),
                ("site", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="platform_product_details", to="masterdata.countrysitemaster")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="product_details", to="masterdata.storemaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="platform_product_details", to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "platform_id", "store_id", "platform_product_id", "platform_variant_id"],
                "constraints": [models.UniqueConstraint(fields=("tenant", "platform", "store", "platform_variant_id"), name="uniq_platform_product_variant")],
                "indexes": [
                    models.Index(fields=("tenant", "platform", "store"), name="idx_platform_product_store"),
                    models.Index(fields=("tenant", "internal_sku"), name="idx_platform_product_sku"),
                    models.Index(fields=("tenant", "sales_status"), name="idx_platform_product_status"),
                ],
            },
        ),
    ]
