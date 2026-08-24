from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0014_platformintegrationconfig_callback_url_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_operation_id_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="platformintegrationconfig",
            name="credential_status",
            field=models.CharField(
                choices=[
                    ("unconfigured", "Unconfigured"),
                    ("configured", "Configured"),
                    ("expiring", "Expiring"),
                    ("expired", "Expired"),
                    ("revoked", "Revoked"),
                    ("reconcile_required", "Reconcile required"),
                ],
                default="unconfigured",
                max_length=30,
            ),
        ),
    ]

