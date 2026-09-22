from django.db import migrations


CONFIG_KEY = "influencers.bd.performance"


def simplify_bd_config(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition = definition_model.objects.filter(config_key=CONFIG_KEY).first()
    if definition is None:
        return
    default_value = dict(definition.default_value or {})
    default_value.pop("default_currency", None)
    default_value.pop("default_attribution", None)
    default_value.setdefault("sample_video_overdue_days", 20)
    default_value.setdefault("sample_overdue_notification_enabled", False)
    definition_model.objects.filter(pk=definition.pk).update(
        default_value=default_value,
        description="BD指标视图、每日订单归因补偿、送样逾期时长和站内提醒开关。",
    )


class Migration(migrations.Migration):
    dependencies = [("influencers", "0023_add_sample_overdue_config")]

    operations = [migrations.RunPython(simplify_bd_config, migrations.RunPython.noop)]
