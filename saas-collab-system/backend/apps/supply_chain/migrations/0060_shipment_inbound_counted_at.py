from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("supply_chain", "0059_fee_revision_quantity_method")]

    operations = [
        migrations.AddField(
            model_name="suppliershipment",
            name="inbound_counted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
