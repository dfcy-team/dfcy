from django.db import migrations, models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone


def migrate_status_baseline(apps, schema_editor):
    SampleFulfillment = apps.get_model("influencers", "SampleFulfillment")
    FulfillmentStatusEvent = apps.get_model("influencers", "FulfillmentStatusEvent")
    InfluencerRestriction = apps.get_model("influencers", "InfluencerRestriction")
    VideoResult = apps.get_model("influencers", "VideoResult")
    now = timezone.now()

    restrictions = InfluencerRestriction.objects.filter(
        tenant_id=OuterRef("tenant_id"),
        influencer_id=OuterRef("influencer_id"),
        is_blacklisted=True,
    )
    published_videos = VideoResult.objects.filter(
        tenant_id=OuterRef("tenant_id"),
        sample_fulfillment_id=OuterRef("pk"),
        published_at__isnull=False,
    )
    rows = SampleFulfillment.objects.filter(status__in=("processing", "creating", "blank")).annotate(
        has_blacklist=Exists(restrictions),
        has_published_video=Exists(published_videos),
    )
    for fulfillment in rows.iterator():
        if fulfillment.has_blacklist:
            mapped = "blacklisted"
        elif fulfillment.has_published_video:
            mapped = "published"
        elif fulfillment.video_deadline_at and fulfillment.video_deadline_at < now:
            mapped = "overdue"
        elif str(fulfillment.sample_order_no or "").strip() or fulfillment.shipped_at:
            mapped = "shipped"
        else:
            mapped = "pending"

        event_mapping = {
            "blank": mapped,
            "processing": mapped,
            "creating": mapped,
        }
        events = FulfillmentStatusEvent.objects.filter(fulfillment_id=fulfillment.pk).filter(
            Q(from_status__in=event_mapping) | Q(to_status__in=event_mapping)
        )
        for event in events.iterator():
            changes = {}
            if event.from_status in event_mapping:
                changes["from_status"] = event_mapping[event.from_status]
            if event.to_status in event_mapping:
                changes["to_status"] = event_mapping[event.to_status]
            FulfillmentStatusEvent.objects.filter(pk=event.pk).update(**changes)
        SampleFulfillment.objects.filter(pk=fulfillment.pk).update(status=mapped)


class Migration(migrations.Migration):
    dependencies = [("influencers", "0011_tiktok_video_data_layer")]

    operations = [
        migrations.RunPython(migrate_status_baseline, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="samplefulfillment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("shipped", "Shipped"),
                    ("delivered", "Delivered"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                    ("published", "Published"),
                    ("live_creator", "Live creator"),
                    ("overdue", "Overdue"),
                    ("blacklisted", "Blacklisted"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
