from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0016_fulfillment_status_import_identity")]

    operations = [
        migrations.AddField(
            model_name="importbatch",
            name="manifest_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
