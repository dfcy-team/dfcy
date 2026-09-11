from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0025_warehouse_credentials")]
    operations = [
        migrations.AddField(
            model_name="oauthstatesession", name="configuration_digest",
            field=models.CharField(max_length=64, blank=True, default=""),
        ),
    ]
