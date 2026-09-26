from django.db import migrations


CONFIG_KEY = "system.module.release_control"
MODULE_CODES = (
    "core", "masterdata", "product_development", "supply_chain", "inventory",
    "global_listing", "sales", "influencer", "finance", "analytics", "decision",
    "reports", "workflow", "rpa", "api_integrations", "system", "governance",
)


def seed_module_release_definition(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition_model.objects.update_or_create(
        config_key=CONFIG_KEY,
        defaults={
            "scope_type": "system",
            "value_type": "json",
            "default_value": {"modules": {code: "enabled" for code in MODULE_CODES}},
            "is_sensitive": False,
            "requires_approval": True,
            "description": "System-level module release controls, independent of production integration runtime settings.",
        },
    )


def remove_module_release_definition(apps, schema_editor):
    apps.get_model("configcenter", "SystemConfigDefinition").objects.filter(config_key=CONFIG_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("configcenter", "0004_configchangelog_activate_action")]

    operations = [migrations.RunPython(seed_module_release_definition, remove_module_release_definition)]
