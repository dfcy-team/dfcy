from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("marketplace_imports", "0002_marketplaceimportbatch_active_attempt_id_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="marketplaceimportbatchattempt",
            options={"base_manager_name": "objects", "ordering": ["created_at", "id"]},
        ),
    ]
