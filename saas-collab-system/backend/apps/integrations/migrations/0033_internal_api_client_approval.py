import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def disable_existing_clients(apps, schema_editor):
    client = apps.get_model("integrations", "InternalAPIClient")
    client.objects.all().update(status="disabled", approval_status="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0032_internal_api_client"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name="InternalAPIClientUsage", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("window_start", models.DateTimeField()),
            ("request_count", models.PositiveIntegerField(default=0)),
            ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="usage_windows", to="integrations.internalapiclient")),
        ], options={"constraints": [models.UniqueConstraint(fields=("client", "window_start"), name="uniq_internal_api_client_minute")]}),
        migrations.AddField(model_name="internalapiclient", name="approval_status", field=models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=16)),
        migrations.AddField(model_name="internalapiclient", name="approved_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_internal_api_clients", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="internalapiclient", name="approved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="internalapiclient", name="reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="internalapiclient", name="rejection_reason", field=models.CharField(blank=True, max_length=500)),
        migrations.AlterField(model_name="internalapiclient", name="status", field=models.CharField(choices=[("active", "Active"), ("disabled", "Disabled")], default="disabled", max_length=16)),
        migrations.RunPython(disable_existing_clients, migrations.RunPython.noop),
    ]
