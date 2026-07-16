from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("rpa", "0003_rpapagesignature_rpataskattempt_rpaevidence_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rpaagent",
            name="execution_mode",
            field=models.CharField(
                choices=[
                    ("mock", "Mock"),
                    ("dry_run", "Dry run"),
                    ("production_disabled", "Production disabled"),
                ],
                default="dry_run",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="manual_assigned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="manual_assignee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_rpa_manual_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="rpatask",
            name="manual_reason",
            field=models.TextField(blank=True),
        ),
    ]
