import django.db.models.deletion
from datetime import timedelta

from django.conf import settings
from django.db import migrations, models


def backfill_video_deadlines(apps, schema_editor):
    fulfillment_model = apps.get_model("influencers", "SampleFulfillment")
    pending = []
    queryset = fulfillment_model.objects.filter(video_deadline_at__isnull=True).only(
        "id", "sample_sent_at", "shipped_at", "created_at", "video_deadline_at"
    )
    for fulfillment in queryset.iterator(chunk_size=500):
        base_time = fulfillment.shipped_at or fulfillment.sample_sent_at or fulfillment.created_at
        if base_time is None:
            continue
        fulfillment.video_deadline_at = base_time + timedelta(days=20)
        pending.append(fulfillment)
        if len(pending) >= 500:
            fulfillment_model.objects.bulk_update(pending, ["video_deadline_at"], batch_size=500)
            pending.clear()
    if pending:
        fulfillment_model.objects.bulk_update(pending, ["video_deadline_at"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("influencers", "0008_influencer_extension_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="samplefulfillment",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="deleted_sample_fulfillments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="link_type",
            field=models.CharField(
                choices=[
                    ("DRJL", "BD建联"),
                    ("YYJL", "运营建联"),
                    ("PKDJ", "PK 对接"),
                    ("ZBDR", "直播达人"),
                    ("TKOne", "TKOne"),
                ],
                default="DRJL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="quick_tags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="samplefulfillment",
            name="video_deadline_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_video_deadlines, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="samplefulfillment",
            index=models.Index(
                fields=["tenant", "is_deleted", "video_deadline_at"],
                name="idx_sample_deadline",
            ),
        ),
    ]
