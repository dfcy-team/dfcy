from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0003_supplypurchaseorder_creation_idempotency_key_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplypurchaseorderevent",
            name="request_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="supplypurchaseorderevent",
            name="response_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
