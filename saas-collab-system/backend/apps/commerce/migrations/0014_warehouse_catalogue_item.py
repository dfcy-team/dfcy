from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("commerce", "0013_salesorder_cancellation_pending"),
    ]

    operations = [
        migrations.CreateModel(
            name="WarehouseCatalogueItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_sku_key", models.CharField(max_length=128)),
                ("source_sku", models.CharField(max_length=64)),
                ("mapping_rule", models.CharField(max_length=64)),
                ("source_data", models.JSONField()),
                ("observed_at", models.DateTimeField()),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.warehousemaster")),
                ("internal_sku", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="products.productsku")),
            ],
            options={"constraints": [
                models.UniqueConstraint(
                    fields=("tenant", "warehouse", "source_sku_key"),
                    name="commerce_warehouse_catalogue_identity",
                ),
            ]},
        ),
    ]
