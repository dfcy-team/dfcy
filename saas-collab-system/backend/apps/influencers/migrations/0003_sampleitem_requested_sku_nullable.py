from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def block_reverse(apps, schema_editor):
    raise IrreversibleError(
        "SampleItem.requested_sku NULL values cannot be represented safely by migration 0002; use a forward fix or restore a backup."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("influencers", "0002_importbatch_externalsourcerecord_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sampleitem",
            name="requested_sku",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.RunPython(migrations.RunPython.noop, reverse_code=block_reverse),
    ]
