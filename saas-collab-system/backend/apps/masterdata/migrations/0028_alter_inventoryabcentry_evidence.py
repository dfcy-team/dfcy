from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0027_inventory_abc_composite"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inventoryabcentry",
            name="evidence",
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
