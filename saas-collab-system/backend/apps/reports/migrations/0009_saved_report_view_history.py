import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_revisions(apps, schema_editor):
    View = apps.get_model("reports", "SavedReportView")
    Revision = apps.get_model("reports", "SavedReportViewRevision")
    batch = []
    for view in View.objects.all().iterator(chunk_size=500):
        view.version = 1
        view.is_archived = False
        batch.append(view)
        if len(batch) >= 500:
            View.objects.bulk_update(batch, ["version", "is_archived"], batch_size=500)
            Revision.objects.bulk_create([
                Revision(view_id=item.pk, version=1, config=item.config, name=item.name,
                         is_shared=item.is_shared, action="baseline", actor_id=item.owner_id)
                for item in batch
            ], batch_size=500)
            batch.clear()
    if batch:
        View.objects.bulk_update(batch, ["version", "is_archived"], batch_size=500)
        Revision.objects.bulk_create([
            Revision(view_id=item.pk, version=1, config=item.config, name=item.name,
                     is_shared=item.is_shared, action="baseline", actor_id=item.owner_id)
            for item in batch
        ], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0008_saved_views_and_source_scope"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="savedreportview", name="version", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name="savedreportview", name="is_archived", field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name="SavedReportViewRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()), ("config", models.JSONField(default=dict)),
                ("name", models.CharField(max_length=100)),
                ("is_shared", models.BooleanField(default=False)),
                ("action", models.CharField(choices=[("baseline", "迁移登记基线"), ("create", "Create"), ("update", "Update"), ("archive", "Archive")], max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="saved_report_view_revisions", to=settings.AUTH_USER_MODEL)),
                ("view", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="reports.savedreportview")),
            ],
            options={"ordering": ["version"]},
        ),
        migrations.AddConstraint(model_name="savedreportviewrevision", constraint=models.UniqueConstraint(fields=("view", "version"), name="uniq_saved_view_revision")),
        migrations.RunPython(backfill_revisions, migrations.RunPython.noop),
    ]
