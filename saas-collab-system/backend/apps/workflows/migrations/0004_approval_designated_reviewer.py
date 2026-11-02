import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0003_report_exception_source"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalrequest",
            name="designated_reviewer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="designated_workflow_approvals", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="workflow_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
