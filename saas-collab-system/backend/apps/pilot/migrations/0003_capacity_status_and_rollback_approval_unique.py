from django.db import migrations, models


def align_capacity_statuses_and_empty_approvals(apps, schema_editor):
    CapacityObservation = apps.get_model("pilot", "CapacityObservation")
    CapacityObservation.objects.filter(status="valid").update(status="normal")
    CapacityObservation.objects.filter(status="partial").update(status="warning")
    CapacityObservation.objects.filter(status="missing").update(status="unknown")

    ReleasePlan = apps.get_model("pilot", "ReleasePlan")
    ReleasePlan.objects.filter(rollback_approval_ref="").update(rollback_approval_ref=None)


class Migration(migrations.Migration):

    dependencies = [
        ("pilot", "0002_pilotauditevent_outcome_error_code"),
    ]

    operations = [
        migrations.RunPython(align_capacity_statuses_and_empty_approvals, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="capacityobservation",
            name="status",
            field=models.CharField(
                choices=[
                    ("normal", "Normal"),
                    ("warning", "Warning"),
                    ("critical", "Critical"),
                    ("unknown", "Unknown"),
                    ("stale", "Stale"),
                ],
                default="unknown",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="releaseplan",
            name="rollback_approval_ref",
            field=models.CharField(blank=True, max_length=160, null=True, unique=True),
        ),
    ]
