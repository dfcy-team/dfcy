from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("integrations", "0020_connection_capability"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncAlertIncident",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("open", "Open"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved")], default="open", max_length=20)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("occurrence_count", models.PositiveIntegerField(default=1)),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                ("masked_message", models.TextField(blank=True)),
                ("resolution_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("acknowledged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="acknowledged_sync_alert_incidents", to=settings.AUTH_USER_MODEL)),
                ("assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_sync_alert_incidents", to=settings.AUTH_USER_MODEL)),
                ("last_sync_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="latest_for_alert_incidents", to="integrations.syncrun")),
                ("notification", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sync_alert_incidents", to="audit.notificationmessage")),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_sync_alert_incidents", to=settings.AUTH_USER_MODEL)),
                ("sync_job", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="alert_incident", to="integrations.syncjob")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sync_alert_incidents", to="tenants.tenant")),
            ],
            options={
                "ordering": ["-updated_at", "-id"],
                "indexes": [models.Index(fields=["tenant", "status"], name="idx_sync_incident_status")],
            },
        ),
    ]
