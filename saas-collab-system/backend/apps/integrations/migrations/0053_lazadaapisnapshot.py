import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0051_ads_authorization_cleanup"),
        ("tenants", "0002_department_leader_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name="LazadaApiSnapshot",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("operation", models.CharField(max_length=60)),
            ("parameters", models.JSONField(default=dict)),
            ("response", models.JSONField(default=dict)),
            ("response_hash", models.CharField(max_length=64)),
            ("status", models.CharField(max_length=20)),
            ("error_code", models.CharField(blank=True, max_length=80)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.marketplacestoreauthorization")),
            ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
        ],
        options={"ordering":["-id"], "indexes":[models.Index(fields=["tenant", "authorization", "created_at"], name="idx_laz_api_snapshot")]},
    )]
