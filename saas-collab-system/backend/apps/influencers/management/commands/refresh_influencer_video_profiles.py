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
        gmv_by_currency = {}
        currency_rows = VideoResult.objects.filter(tenant=tenant).values(
            "influencer_id", "currency"
        ).annotate(total_gmv=Sum("gmv"))
        for row in currency_rows.iterator(chunk_size=1000):
            currency = str(row["currency"] or "UNKNOWN").upper()
            gmv_by_currency.setdefault(row["influencer_id"], {})[currency] = row["total_gmv"] or 0
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
                currency_totals = gmv_by_currency.get(row["influencer_id"], {})
                history["video_gmv_by_currency"] = {
                    currency: str(value) for currency, value in sorted(currency_totals.items())
                }
                history["video_gmv_mixed_currency"] = len(currency_totals) > 1
                update_fields = ["average_video_views", "historical_performance", "updated_at"]
                original_gmv = profile.historical_gmv
                original_orders = profile.historical_orders
                existing_source = history.get("historical_gmv_source")
                can_replace_summary = existing_source == "video_results" or (
                    profile.historical_gmv == 0 and profile.historical_orders == 0
                )
                if len(currency_totals) == 1:
                    currency, total_gmv = next(iter(currency_totals.items()))
                    history.update({
                        "video_total_gmv": str(total_gmv),
                        "video_gmv_currency": currency,
                    })
                    if can_replace_summary:
                        profile.historical_gmv = total_gmv
                        profile.historical_orders = row["total_orders"] or 0
                        history["historical_gmv_source"] = "video_results"
                        history["historical_gmv_currency"] = currency
                else:
                    history["video_total_gmv"] = None
                    history["video_gmv_currency"] = None
                    if existing_source == "video_results":
                        profile.historical_gmv = 0
                        profile.historical_orders = 0
                        history.pop("historical_gmv_source", None)
                        history.pop("historical_gmv_currency", None)
                if profile.historical_gmv != original_gmv:
                    update_fields.append("historical_gmv")
                if profile.historical_orders != original_orders:
                    update_fields.append("historical_orders")
                average_views = int(row["average_views"] or 0)
                if (
                    profile.average_video_views == average_views
                    and profile.historical_performance == history
                    and profile.historical_gmv == original_gmv
                    and profile.historical_orders == original_orders
                ):
                    unchanged += 1
                    continue
                profile.average_video_views = average_views
                profile.historical_performance = history
                profile.save(update_fields=list(dict.fromkeys(update_fields)))
                updated += 1
            if not options["apply"]:
                transaction.set_rollback(True)
        self.stdout.write(
            f"mode={'apply' if options['apply'] else 'dry-run'} updated={updated} "
            f"unchanged={unchanged} missing_profile={missing_profile}"
        )
