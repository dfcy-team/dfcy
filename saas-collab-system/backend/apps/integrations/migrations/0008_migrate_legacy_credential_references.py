import importlib

from django.db import migrations


migration_0007 = importlib.import_module(
    "apps.integrations.migrations.0007_alter_apiintegrationconfig_options_and_more"
)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("integrations", "0007_alter_apiintegrationconfig_options_and_more"),
    ]

    operations = [
        migrations.RunPython(
            migration_0007.migrate_synthetic_credential_references,
            migrations.RunPython.noop,
        ),
    ]
