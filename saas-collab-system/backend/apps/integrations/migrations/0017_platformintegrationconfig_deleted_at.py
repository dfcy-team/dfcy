from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0016_commerce_platform_and_resource_choices")]

    operations = [
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
