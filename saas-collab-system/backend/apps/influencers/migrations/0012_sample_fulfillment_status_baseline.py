from django.db import migrations, models
from django.db.models import Exists, OuterRef, Q
from django.db.models.query import QuerySet
from django.db.models.functions import Trim
from django.utils import timezone


LEGACY_STATUSES = ("processing", "creating", "blank")
FORWARD_STATUSES = ("pending", "shipped", "published", "overdue", "blacklisted")


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

    def rows():
        return SampleFulfillment.objects.filter(status__in=LEGACY_STATUSES).annotate(
            has_blacklist=Exists(restrictions),
            has_published_video=Exists(published_videos),
            trimmed_sample_order_no=Trim("sample_order_no"),
        )

    # Apply the same priority as the former row mapper without holding one
    # Python object per fulfillment or issuing one UPDATE per row.
    QuerySet.update(rows().filter(has_blacklist=True), status="blacklisted")
    QuerySet.update(
        rows().filter(has_blacklist=False, has_published_video=True),
        status="published",
    )
    QuerySet.update(
        rows().filter(
            has_blacklist=False,
            has_published_video=False,
            video_deadline_at__lt=now,
        ),
        status="overdue",
    )
    QuerySet.update(
        rows().filter(
            has_blacklist=False,
            has_published_video=False,
            trimmed_sample_order_no__isnull=False,
        ).filter(
            ~Q(trimmed_sample_order_no="") | Q(shipped_at__isnull=False)
        ),
        status="shipped",
    )
    QuerySet.update(rows(), status="pending")

    # Legacy event values follow the final status of their fulfillment. The
    # two field updates are set-based and leave unrelated event values intact.
    for mapped in FORWARD_STATUSES:
        events = FulfillmentStatusEvent.objects.filter(fulfillment__status=mapped)
        QuerySet.update(
            events.filter(from_status__in=LEGACY_STATUSES),
            from_status=mapped,
        )
        QuerySet.update(
            events.filter(to_status__in=LEGACY_STATUSES),
            to_status=mapped,
        )


def restore_status_baseline(apps, schema_editor):
    SampleFulfillment = apps.get_model("influencers", "SampleFulfillment")
    FulfillmentStatusEvent = apps.get_model("influencers", "FulfillmentStatusEvent")

    # 0011 has no blacklisted value. Cancellation is the compatible terminal
    # value and is also safe for the reverse event history.
    QuerySet.update(
        SampleFulfillment.objects.filter(status="blacklisted"),
        status="cancelled",
    )
    QuerySet.update(
        FulfillmentStatusEvent.objects.filter(from_status="blacklisted"),
        from_status="cancelled",
    )
    QuerySet.update(
        FulfillmentStatusEvent.objects.filter(to_status="blacklisted"),
        to_status="cancelled",
    )


class Migration(migrations.Migration):
    dependencies = [("influencers", "0011_tiktok_video_data_layer")]

    operations = [
        migrations.RunPython(migrate_status_baseline, restore_status_baseline),
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
