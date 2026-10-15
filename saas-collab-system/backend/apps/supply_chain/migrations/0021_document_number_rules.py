from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("supply_chain", "0020_archive_navigation"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentNumberRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("kind", models.CharField(choices=[("operating_order", "运营订货单"), ("purchase_order", "采购单"), ("supplier_shipment", "供应商发货单"), ("dispatch_batch", "集运批次"), ("inbound_order", "入库单")], max_length=32)),
                ("enabled", models.BooleanField(default=False)),
                ("include_country", models.BooleanField(default=False)),
                ("country_prefixes", models.JSONField(blank=True, default=dict)),
                ("prefix", models.CharField(max_length=12)),
                ("date_format", models.CharField(choices=[("YYYYMMDD", "YYYYMMDD"), ("YYMMDD", "YYMMDD"), ("YYYYMM", "YYYYMM"), ("YYYY", "YYYY"), ("none", "none")], max_length=8)),
                ("separator", models.CharField(choices=[("-", "-"), ("_", "_"), ("none", "none")], max_length=4)),
                ("sequence_width", models.PositiveSmallIntegerField(default=4)),
                ("reset_period", models.CharField(choices=[("day", "day"), ("month", "month"), ("year", "year"), ("never", "never")], max_length=8)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("tenant", "kind"), name="sc2_number_rule_tenant_kind")]},
        ),
        migrations.CreateModel(
            name="DocumentNumberCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("kind", models.CharField(choices=[("operating_order", "运营订货单"), ("purchase_order", "采购单"), ("supplier_shipment", "供应商发货单"), ("dispatch_batch", "集运批次"), ("inbound_order", "入库单")], max_length=32)),
                ("country_code", models.CharField(blank=True, default="", max_length=8)),
                ("period_key", models.CharField(max_length=32)),
                ("value", models.PositiveBigIntegerField(default=0)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.tenant")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("tenant", "kind", "country_code", "period_key"), name="sc2_number_counter_period"),
                models.CheckConstraint(condition=models.Q(("value__gte", 0)), name="sc2_number_counter_nonnegative"),
            ]},
        ),
    ]
