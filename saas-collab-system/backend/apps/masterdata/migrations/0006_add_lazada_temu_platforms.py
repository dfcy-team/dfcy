from django.db import migrations, models


PLATFORM_SEEDS = (
    ("lazada", "LAZADA"),
    ("temu", "TEMU"),
)


def seed_lazada_temu(apps, schema_editor):
    tenant_model = apps.get_model("tenants", "Tenant")
    platform_model = apps.get_model("masterdata", "PlatformMaster")
    for tenant in tenant_model.objects.all().iterator():
        for code, name in PLATFORM_SEEDS:
            platform, created = platform_model.objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={"name": name, "platform_type": code, "status": "active"},
            )
            if not created:
                updates = {}
                if platform.name != name:
                    updates["name"] = name
                if platform.platform_type != code:
                    updates["platform_type"] = code
                if updates:
                    platform_model.objects.filter(pk=platform.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0005_seed_country_sites")]

    operations = [
        migrations.AlterField(
            model_name="platformmaster",
            name="platform_type",
            field=models.CharField(
                choices=[
                    ("bigseller", "BigSeller"),
                    ("shopee", "Shopee"),
                    ("tiktok", "TikTok"),
                    ("lazada", "LAZADA"),
                    ("temu", "TEMU"),
                    ("other", "Other"),
                ],
                max_length=30,
            ),
        ),
        migrations.RunPython(seed_lazada_temu, migrations.RunPython.noop),
    ]
