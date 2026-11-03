from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("listings", "0005_platformproductdetail_platform_image_url")]
    operations = [
        migrations.AddField(
            model_name="platformproductdetail",
            name="platform_image_source",
            field=models.CharField(max_length=16, blank=True, default=""),
        ),
    ]
