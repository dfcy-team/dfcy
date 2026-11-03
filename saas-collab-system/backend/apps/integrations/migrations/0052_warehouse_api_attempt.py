from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0051_ads_authorization_cleanup"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name="WarehouseApiAttempt",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("operation", models.CharField(max_length=60)),
            ("key_hash", models.CharField(max_length=64)),
            ("payload_hash", models.CharField(max_length=64)),
            ("status", models.CharField(max_length=20, default="running", choices=[
                ("running", "执行中"), ("succeeded", "成功"), ("rejected", "仓库拒绝"), ("unknown", "结果待核实")])),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("finished_at", models.DateTimeField(null=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("authorization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.warehouseauthorization")),
            ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
        ],
        options={
            "constraints": [models.UniqueConstraint(fields=("tenant", "key_hash"), name="uniq_warehouse_api_attempt")],
            "indexes": [models.Index(fields=["tenant", "authorization", "created_at"], name="idx_wh_api_attempt")],
        },
    )]
