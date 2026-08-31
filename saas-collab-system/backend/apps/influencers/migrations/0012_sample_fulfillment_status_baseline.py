from django.db import migrations, models
from django.db.models import Exists, OuterRef, Q
from django.db.models.query import QuerySet
from django.db.models.functions import Trim
from django.utils import timezone


LEGACY_STATUSES = ("processing", "creating", "blank")


def migrate_status_baseline(apps, schema_editor):
    SampleFulfillment = apps.get_model("influencers", "SampleFulfillment")
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

class Migration(migrations.Migration):
    dependencies = [("influencers", "0011_tiktok_video_data_layer")]

    operations = [
        # This maps legacy statuses using current fulfillment facts. The source
        # status cannot be reconstructed after migration, so it must not be
        # downgraded as though the operation were reversible.
        migrations.RunPython(migrate_status_baseline),
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
