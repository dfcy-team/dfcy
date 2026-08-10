from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("packing", "0002_packingapiidempotencyrecord"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="packingapiidempotencyrecord",
            constraint=models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="uniq_pack_api_tenant_key",
            ),
        ),
    ]
