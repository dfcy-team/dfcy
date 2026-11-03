import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # Independent of the pending warehouse migration; can be applied in isolation.
    dependencies = [
        ("integrations", "0053_lazadaapisnapshot"),
        ("masterdata", "0001_initial"),
    ]
    operations = [migrations.CreateModel(
        name="LazadaAdvertisingDailySpend",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("report_date", models.DateField()),
            ("currency", models.CharField(max_length=8)),
            ("report_timezone", models.CharField(max_length=64)),
            ("spend", models.DecimalField(decimal_places=4, max_digits=20)),
            ("dimensions", models.JSONField(default=dict)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("overview_snapshot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="overview_spend_rows", to="integrations.lazadaapisnapshot")),
            ("source_snapshot", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="daily_spend_rows", to="integrations.lazadaapisnapshot")),
            ("store", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="masterdata.storemaster")),
            ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
        ],
        options={
            "indexes": [models.Index(fields=["tenant", "report_date", "store"], name="idx_lazada_ads_date")],
            "constraints": [models.UniqueConstraint(fields=["tenant", "store", "report_date"], name="uniq_lazada_ads_store_day"),
                            models.CheckConstraint(condition=models.Q(spend__gte=0), name="lazada_ads_spend_nonnegative")],
        },
    )]
