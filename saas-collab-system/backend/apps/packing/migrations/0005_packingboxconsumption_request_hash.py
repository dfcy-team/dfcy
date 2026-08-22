from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("packing", "0004_packing_batch_line_allocation_and_box_consumption")]

    operations = [
        migrations.AddField(
            model_name="packingboxconsumption",
            name="request_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
