import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0006_add_lazada_temu_platforms"),
        ("accounts", "0003_user_full_name_and_profile_departments"),
        ("products", "0013_productsku_product_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="storemaster", name="platform_store_name",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
        migrations.AddField(
            model_name="storemaster", name="category",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="store_masters", to="products.productcategory"),
        ),
        migrations.AddField(
            model_name="storemaster", name="operator",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="operated_store_masters", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="storemaster", name="bd",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="bd_store_masters", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="storemaster", name="leader",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="led_store_masters", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="storemaster", name="is_connected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="storemaster", name="tactical_client",
            field=models.CharField(blank=True, default="", max_length=160),
        ),
    ]
