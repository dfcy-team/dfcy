from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0036_feishuloginsession"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="FeishuDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("app_id", models.CharField(max_length=120)),
                ("open_id", models.CharField(max_length=120)),
                ("idempotency_key", models.CharField(max_length=200)),
                ("payload", models.JSONField(default=dict)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(null=True)),
                ("lease_until", models.DateTimeField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tenants.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("operation", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="delivery", to="integrations.feishuoperation")),
                ("rule", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="integrations.feishuconfigrule")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("tenant", "idempotency_key"), name="uniq_feishu_delivery_key")]},
        ),
    ]
