from django.db import migrations, models


class Migration(migrations.Migration):
    # Keep the UAT lease migration on the committed accounts leaf.  The
    # unrelated full_name/departments migration may be present as a parallel
    # local branch, but UAT credentials must not depend on it.
    dependencies = [("accounts", "0002_miniappidentity")]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="uat_credential_activated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="uat_credential_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="uat_credential_batch_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="customuser",
            name="uat_credential_status",
            field=models.CharField(default="never", max_length=16),
        ),
    ]
