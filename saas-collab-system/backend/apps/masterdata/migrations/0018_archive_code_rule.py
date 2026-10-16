from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0017_warehouse_business_metadata")]

    operations = [
        migrations.CreateModel(
            name="ArchiveCodeRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("supplier", "供应商档案"), ("freight", "货运公司")], max_length=16)),
                ("is_enabled", models.BooleanField(default=False)),
                ("prefix", models.CharField(max_length=16)),
                ("separator", models.CharField(blank=True, default="", max_length=1)),
                ("sequence_width", models.PositiveSmallIntegerField(default=3)),
                ("next_sequence", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="archive_code_rules", to="tenants.tenant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="archivecoderule",
            constraint=models.UniqueConstraint(fields=("tenant", "kind"), name="uniq_archive_code_rule_tenant_kind"),
        ),
    ]
