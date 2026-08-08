# Credential custody metadata boundary.
#
# Secrets remain in the independent local custody store.  The integration
# database receives only opaque IDs and lifecycle metadata.  Legacy ciphertext
# columns are intentionally retained for a compatibility/read-only migration
# window; new application writes must not populate them.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0006_syncjob_lock_acquired_at_syncjob_lock_expires_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_id",
            field=models.CharField(blank=True, db_index=True, max_length=96),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="token_id",
            field=models.CharField(blank=True, max_length=96),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_mask",
            field=models.CharField(blank=True, default="***", max_length=16),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("expired", "Expired"),
                    ("revoked", "Revoked"),
                    ("placeholder", "Placeholder"),
                ],
                default="placeholder",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformintegrationconfig",
            name="credential_operation_id_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="credential_id",
            field=models.CharField(blank=True, db_index=True, max_length=96),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="token_id",
            field=models.CharField(blank=True, max_length=96),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="credential_mask",
            field=models.CharField(blank=True, default="***", max_length=16),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="credential_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="credential_revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="apiintegrationconfig",
            name="credential_operation_id_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="apiintegrationconfig",
            name="credential_status",
            field=models.CharField(
                choices=[
                    ("placeholder", "Placeholder"),
                    ("active", "Active"),
                    ("rotation_required", "Rotation required"),
                    ("expired", "Expired"),
                    ("revoked", "Revoked"),
                ],
                default="placeholder",
                max_length=30,
            ),
        ),
    ]
