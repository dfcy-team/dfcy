from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0016_supplier_payment_terms"),
    ]

    operations = [
        migrations.AddField("warehousemaster", "address", models.CharField(blank=True, max_length=500)),
        migrations.AddField("warehousemaster", "region", models.CharField(blank=True, max_length=80)),
        migrations.AddField("warehousemaster", "legacy_codes", models.JSONField(blank=True, default=list)),
        migrations.AddField("warehousemaster", "notes", models.TextField(blank=True)),
        migrations.AddField("warehousemaster", "supply_version", models.PositiveIntegerField(default=1)),
    ]
