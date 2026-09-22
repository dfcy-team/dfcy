from django.db import migrations


CONFIG_KEY = "influencers.bd.performance"


def add_sample_overdue_config(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition = definition_model.objects.filter(config_key=CONFIG_KEY).first()
    if definition is None:
        return
    default_value = dict(definition.default_value or {})
    default_value.setdefault("sample_video_overdue_days", 20)
    definition_model.objects.filter(pk=definition.pk).update(
        default_value=default_value,
        description=(
            "BD绩效默认展示口径、每日订单归因补偿开关和送样逾期时长。"
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0023_sampleitem_cost_version"),
    ]

    operations = [migrations.RunPython(add_sample_overdue_config, migrations.RunPython.noop)]
