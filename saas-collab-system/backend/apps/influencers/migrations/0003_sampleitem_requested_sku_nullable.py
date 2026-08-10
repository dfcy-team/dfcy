from django.db import migrations, models


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
    ]
