from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant

from apps.influencers.services import mark_overdue_sample_fulfillments


class Command(BaseCommand):
    help = "Mark expired sample fulfillments overdue without touching external systems."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", "--tenant", dest="tenant_id", type=int)
        parser.add_argument("--actor-id", type=int)
        parser.add_argument(
            "--now",
            dest="now",
            help="Optional ISO-8601 timestamp for deterministic dry-run tests.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        if options.get("now"):
            now = parse_datetime(options["now"])
            if now is None:
                self.stderr.write(self.style.ERROR("--now must be an ISO-8601 datetime."))
                return 2
            if timezone.is_naive(now):
                now = timezone.make_aware(now, timezone.get_current_timezone())

        tenants = Tenant.objects.order_by("id")
        if options.get("tenant_id"):
            tenants = tenants.filter(pk=options["tenant_id"])

        total_marked = 0
        total_skipped = 0
        for tenant in tenants:
            actor_queryset = CustomUser.objects.filter(
                tenant=tenant,
                is_active=True,
                user_type=CustomUser.UserType.INTERNAL,
            ).order_by("id")
            if options.get("actor_id"):
                actor_queryset = actor_queryset.filter(pk=options["actor_id"])
            actor = actor_queryset.first()
            if actor is None:
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipped tenant {tenant.pk}: no active internal actor available."
                    )
                )
                continue
            result = mark_overdue_sample_fulfillments(actor=actor, tenant=tenant, now=now)
            total_marked += result["marked"]
            total_skipped += result["skipped_with_video"]

        self.stdout.write(
            self.style.SUCCESS(
                f"marked={total_marked} skipped_with_video={total_skipped}"
            )
        )
