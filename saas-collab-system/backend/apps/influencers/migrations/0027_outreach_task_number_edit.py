from django.db import migrations, models


CONFIG_KEY = "influencers.bd.performance"


def add_number_edit_default(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition = definition_model.objects.filter(config_key=CONFIG_KEY).first()
    if definition is None:
        return
    default_value = dict(definition.default_value or {})
    default_value.setdefault("outreach_task_number_edit_enabled", False)
    definition_model.objects.filter(pk=definition.pk).update(default_value=default_value)


class Migration(migrations.Migration):
    dependencies = [("influencers", "0026_sampleitem_warehouse")]

    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="task_no_manual_override",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(add_number_edit_default, migrations.RunPython.noop),
    ]
