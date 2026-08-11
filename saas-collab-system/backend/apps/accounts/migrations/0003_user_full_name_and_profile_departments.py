from django.db import migrations, models


def copy_primary_departments(apps, schema_editor):
    InternalUserProfile = apps.get_model("accounts", "InternalUserProfile")
    through = InternalUserProfile.departments.through
    rows = [
        through(internaluserprofile_id=profile.id, department_id=profile.department_id)
        for profile in InternalUserProfile.objects.exclude(department_id=None).iterator()
    ]
    if rows:
        through.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_miniappidentity")]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="full_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="internaluserprofile",
            name="departments",
            field=models.ManyToManyField(
                blank=True,
                related_name="assigned_internal_profiles",
                to="tenants.department",
            ),
        ),
        migrations.RunPython(copy_primary_departments, migrations.RunPython.noop),
    ]
