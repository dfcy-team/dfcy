from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0009_expand_platform_catalog")]

    operations = [
        migrations.CreateModel(
            name="PlatformSiteMaster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("site_code", models.SlugField(max_length=60)),
                ("name", models.CharField(max_length=120)),
                ("country_code", models.CharField(max_length=8)),
                ("region_code", models.CharField(blank=True, default="", max_length=32)),
                ("currency_code", models.CharField(blank=True, default="", max_length=8)),
                ("timezone", models.CharField(default="UTC", max_length=60)),
                ("language_codes", models.JSONField(blank=True, default=list)),
                ("api_region", models.CharField(blank=True, default="", max_length=60)),
                ("api_base_url", models.URLField(blank=True, default="", max_length=500)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive")], default="active", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("platform", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="platform_sites", to="masterdata.platformmaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="platform_site_masters", to="tenants.tenant")),
            ],
            options={
                "ordering": ["tenant_id", "platform_id", "site_code"],
                "constraints": [models.UniqueConstraint(fields=("tenant", "platform", "site_code"), name="uniq_platform_site_code")],
            },
        ),
        migrations.AddField(
            model_name="storemaster", name="platform_site",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="stores", to="masterdata.platformsitemaster"),
        ),
        migrations.AddField(model_name="storemaster", name="external_store_id", field=models.CharField(blank=True, default="", max_length=160)),
        migrations.AddField(model_name="storemaster", name="seller_entity_id", field=models.CharField(blank=True, default="", max_length=160)),
        migrations.AddField(
            model_name="storemaster", name="business_model",
            field=models.CharField(choices=[("local", "Local"), ("cross_border", "Cross border"), ("full_managed", "Full managed"), ("semi_managed", "Semi managed"), ("other", "Other")], default="other", max_length=30),
        ),
        migrations.AddField(model_name="storemaster", name="fulfillment_modes", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="storemaster", name="settlement_currency", field=models.CharField(blank=True, default="", max_length=8)),
    ]
