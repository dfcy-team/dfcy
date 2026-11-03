from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("listings", "0004_platform_product_detail_read_indexes")]
    operations = [
        migrations.AddField(
            model_name="platformproductdetail",
            name="platform_image_url",
            field=models.URLField(max_length=2048, blank=True, default=""),
        ),
    ]
