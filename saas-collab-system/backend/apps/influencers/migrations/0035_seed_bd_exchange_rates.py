from django.db import migrations


CONFIG_KEY = "influencers.bd.exchange_rates"


def seed_bd_exchange_rates(apps, schema_editor):
    definition = apps.get_model("configcenter", "SystemConfigDefinition")
    definition.objects.update_or_create(
        config_key=CONFIG_KEY,
        defaults={
            "scope_type": "tenant",
            "value_type": "json",
            "default_value": {"rates": []},
            "is_sensitive": False,
            "requires_approval": True,
            "description": (
                "Approved BD currency-to-CNY schedules by business date. "
                "CNY remains identity 1; uncovered dates and currencies use legacy ExchangeRate facts. "
                "An empty schedule explicitly retains legacy resolution."
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("configcenter", "0004_configchangelog_activate_action"),
        ("influencers", "0034_affiliate_settlement_status"),
    ]

    # Seed the definition only; rollback must preserve approval/audit history.
    operations = [migrations.RunPython(seed_bd_exchange_rates, migrations.RunPython.noop)]
