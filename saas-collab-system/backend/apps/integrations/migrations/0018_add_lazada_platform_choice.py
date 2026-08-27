from django.db import migrations, models


PLATFORM_CHOICES = [
    ("bigseller", "BigSeller"),
    ("lazada", "Lazada"),
    ("shopee", "Shopee"),
    ("tiktok", "TikTok"),
    ("jifeng_wms", "Jifeng WMS"),
    ("mock", "Mock"),
    ("other", "Other"),
]


class Migration(migrations.Migration):
    dependencies = [("integrations", "0017_platformintegrationconfig_deleted_at")]

    operations = [
        migrations.AlterField(
            model_name=model_name,
            name="platform",
            field=models.CharField(choices=PLATFORM_CHOICES, max_length=30),
        )
        for model_name in (
            "apiintegrationconfig",
            "apisynctask",
            "platformintegrationconfig",
            "marketplaceproductmapping",
            "marketplacestoreauthorization",
            "marketplacestoremapping",
            "oauthstatesession",
            "webhookevent",
        )
    ]
