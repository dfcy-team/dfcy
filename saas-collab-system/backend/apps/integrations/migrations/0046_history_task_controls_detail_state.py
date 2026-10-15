import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0045_feishu_binding_session"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="synccursor", name="detail_state", field=models.JSONField(default=dict),
        ),
        migrations.CreateModel(
            name="HistorySyncTaskControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_paused", models.BooleanField(default=False)),
                ("pause_reason", models.CharField(blank=True, max_length=80)),
                ("execution_policy", models.JSONField(default=dict)),
                ("authority_assigned", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("authorized_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="authorized_history_tasks", to=settings.AUTH_USER_MODEL)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="task_controls", to="integrations.historysyncbatch")),
                ("sync_job", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="history_controls", to="integrations.syncjob")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("batch", "sync_job"), name="uniq_history_task_control")]},
        ),
    ]
