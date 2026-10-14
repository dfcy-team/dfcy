from django.db import migrations


CONFIG_KEY = "influencers.bd.exchange_rates"


def disable_bd_exchange_rate_approval(apps, schema_editor):
    definition = apps.get_model("configcenter", "SystemConfigDefinition")
    definition.objects.using(schema_editor.connection.alias).filter(config_key=CONFIG_KEY).update(
        requires_approval=False,
        description=(
            "BD currency-to-CNY schedules take effect on save without approval. "
            "Business dates select the applicable rate; previous versions and audit history remain. "
            "Uncovered dates and currencies retain legacy ExchangeRate resolution."
        ),
    )


class Migration(migrations.Migration):
    dependencies = [("influencers", "0036_affiliate_actual_ads_commission")]

    # Do not activate, edit or delete pre-existing versions, including pending drafts.
    operations = [migrations.RunPython(disable_bd_exchange_rate_approval, migrations.RunPython.noop)]
