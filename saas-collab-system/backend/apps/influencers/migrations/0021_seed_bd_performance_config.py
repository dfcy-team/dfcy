from django.db import migrations


CONFIG_KEY = "influencers.bd.performance"
DEFAULT_VALUE = {
    "default_currency": "CNY",
    "default_attribution": "strict",
    "default_metrics": "core",
    "daily_attribution_reconciliation_enabled": True,
}


def seed_bd_performance_config(apps, schema_editor):
    definition_model = apps.get_model("configcenter", "SystemConfigDefinition")
    definition_model.objects.update_or_create(
        config_key=CONFIG_KEY,
        defaults={
            "scope_type": "tenant",
            "value_type": "json",
            "default_value": DEFAULT_VALUE,
            "is_sensitive": False,
            "requires_approval": True,
            "description": (
                "BD绩效默认币种、默认归因方式、指标视图和每日订单归因补偿开关。"
                "汇率数值继续由按生效日期维护的ExchangeRate记录提供。"
            ),
        },
    )


def remove_bd_performance_config(apps, schema_editor):
    # Preserve configuration history if the code migration is rolled back.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("configcenter", "0004_configchangelog_activate_action"),
        ("influencers", "0020_influencer_query_efficiency"),
    ]
    operations = [migrations.RunPython(seed_bd_performance_config, remove_bd_performance_config)]
