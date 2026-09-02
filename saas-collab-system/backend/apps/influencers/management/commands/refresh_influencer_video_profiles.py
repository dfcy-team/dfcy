from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Avg, Count, Max, Sum

from apps.tenants.models import Tenant

from ...models import InfluencerProfile, VideoResult


class Command(BaseCommand):
    help = "Refresh influencer profile video metrics from imported video results."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(pk=options["tenant_id"])
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist.") from exc

        aggregates = VideoResult.objects.filter(tenant=tenant).values("influencer_id").annotate(
            average_views=Avg("views"),
            total_views=Sum("views"),
            total_orders=Sum("orders"),
            video_count=Count("id"),
            latest_date=Max("metric_date"),
        )
        updated = unchanged = missing_profile = 0
        with transaction.atomic():
            profiles = {
                profile.influencer_id: profile
                for profile in InfluencerProfile.objects.select_for_update().filter(tenant=tenant)
            }
            for row in aggregates.iterator(chunk_size=1000):
                profile = profiles.get(row["influencer_id"])
                if profile is None:
                    missing_profile += 1
                    continue
                history = dict(profile.historical_performance or {})
                history.update({
                    "video_total_views": row["total_views"] or 0,
                    "video_total_orders": row["total_orders"] or 0,
                    "video_count": row["video_count"] or 0,
                    "video_latest_date": row["latest_date"].isoformat() if row["latest_date"] else None,
                })
                average_views = int(row["average_views"] or 0)
                if profile.average_video_views == average_views and profile.historical_performance == history:
                    unchanged += 1
                    continue
                profile.average_video_views = average_views
                profile.historical_performance = history
                profile.save(update_fields=["average_video_views", "historical_performance", "updated_at"])
                updated += 1
            if not options["apply"]:
                transaction.set_rollback(True)
        self.stdout.write(
            f"mode={'apply' if options['apply'] else 'dry-run'} updated={updated} "
            f"unchanged={unchanged} missing_profile={missing_profile}"
        )
