from django.db import migrations, models
import django.db.models.deletion


def classify_myjf_platforms(apps, schema_editor):
    platform_model = apps.get_model("masterdata", "PlatformMaster")
    platform_model.objects.filter(
        code__iexact="myjf",
        platform_type="other",
    ).update(platform_type="warehouse_third_party")


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0008_merge_country_and_store_branches"),
    ]

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
                    ("warehouse_owned", "自营仓服务"),
                    ("warehouse_third_party", "三方仓服务"),
                    ("warehouse_platform", "平台仓服务"),
                    ("other", "Other"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="warehousemaster",
            name="service_platform",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_warehouses",
                to="masterdata.platformmaster",
            ),
        ),
        # Do not rewrite a later operator classification during schema rollback.
        migrations.RunPython(classify_myjf_platforms, migrations.RunPython.noop),
    ]
