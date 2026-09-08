from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("influencers", "0017_importbatch_manifest_digest")]

    operations = [
        migrations.AddField(
            model_name="outreachtask",
            name="source_owner_name_snapshot",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="outreachtask",
            name="source_dispatcher_name_snapshot",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="source_owner_name_snapshot",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddConstraint(
            model_name="outreachtask",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source="feishu_full_20260908")
                    | (
                        models.Q(source_owner_name_snapshot="")
                        & models.Q(source_dispatcher_name_snapshot="")
                    )
                ),
                name="outreach_source_personnel_guard",
            ),
        ),
        migrations.AddConstraint(
            model_name="samplefulfillment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source="feishu_full_20260908")
                    | models.Q(source_owner_name_snapshot="")
                ),
                name="sample_source_personnel_guard",
            ),
        ),
    ]
