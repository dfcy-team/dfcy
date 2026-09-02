from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="operationlog",
            index=models.Index(
                fields=["tenant", "-created_at", "-id"],
                name="idx_operation_log_tenant_time",
            ),
        ),
        migrations.AddIndex(
            model_name="operationlog",
            index=models.Index(
                fields=["tenant", "user", "-created_at", "-id"],
                name="audit_log_tenant_user_time",
            ),
        ),
    ]
