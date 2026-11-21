# Generated manually for the captured production code baseline.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0026_inventory_abc")]

    operations = [
        migrations.AddField(
            model_name="inventoryabcentry",
            name="evidence",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
