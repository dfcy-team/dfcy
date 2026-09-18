from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0028_merge_sync_schedule")]

    operations = [
        migrations.CreateModel(
            name="AutomaticRefreshAttempt",
            fields=[
                ("request_key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("status", models.CharField(default="running", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "tenant",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant"),
                ),
            ],
        ),
    ]
