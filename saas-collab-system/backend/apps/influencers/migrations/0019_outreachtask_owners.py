from django.conf import settings
from django.db import migrations, models


def copy_primary_owner(apps, schema_editor):
    OutreachTask = apps.get_model("influencers", "OutreachTask")
    through = OutreachTask.owners.through
    through.objects.bulk_create(
        [
            through(outreachtask_id=task_id, customuser_id=owner_id)
            for task_id, owner_id in OutreachTask.objects.values_list("id", "owner_id").iterator()
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("influencers", "0018_source_personnel_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="owners",
            field=models.ManyToManyField(
                related_name="assigned_outreach_tasks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(copy_primary_owner, migrations.RunPython.noop),
    ]
