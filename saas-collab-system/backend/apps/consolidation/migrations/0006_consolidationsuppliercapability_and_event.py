from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("consolidation", "0005_alter_consolidationevent_action"),
        ("masterdata", "0002_alter_suppliermaster_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsolidationSupplierCapability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("can_submit_handover", models.BooleanField(default=False)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_consolidation_capabilities", to=settings.AUTH_USER_MODEL)),
                ("supplier", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="consolidation_capabilities", to="masterdata.suppliermaster")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="consolidation_supplier_capabilities", to="tenants.tenant")),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="updated_consolidation_capabilities", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["tenant_id", "supplier_id"],
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "supplier"), name="uniq_consolidation_supplier_capability"),
                    models.CheckConstraint(condition=models.Q(("version__gt", 0)), name="consolidation_capability_version_gt_zero"),
                ],
            },
        ),
        migrations.AlterField(
            model_name="consolidationevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("site_create", "Create site"), ("site_update", "Update site"),
                    ("site_deactivate", "Deactivate site"), ("capability_update", "Update supplier capability"),
                    ("create", "Create consolidation"), ("update", "Update consolidation"),
                    ("allocate", "Allocate box"), ("remove", "Remove box"),
                    ("release", "Release consolidation"), ("receive", "Receive box"),
                    ("transfer", "Transfer box to shipment"), ("handover_submit", "Submit handover evidence"),
                    ("exception", "Mark exception"), ("controlled_release", "Controlled release"),
                    ("ready", "Ready for shipment"), ("cancel", "Cancel consolidation"),
                ],
                max_length=40,
            ),
        ),
    ]
