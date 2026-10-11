"""Bounded derived-index backfill; never edit identities or business timestamps."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet

from apps.influencers.models import Influencer, InfluencerProfile, identity_digest, normalize_tiktok_username
from apps.tenants.models import Tenant


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant_id, limit = options["tenant"], options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("limit must be between 1 and 1000")
        with transaction.atomic():
            if not Tenant.objects.select_for_update().filter(pk=tenant_id).exists():
                raise CommandError("Unknown tenant")
            parent_rows = list(Influencer.objects.filter(
                tenant_id=tenant_id, canonical_handle_digest__isnull=True,
            ).order_by("pk")[:limit])
            profile_ids = list(InfluencerProfile.objects.filter(
                tenant_id=tenant_id, canonical_external_id_digest__isnull=True,
            ).order_by("pk").values_list("pk", "influencer_id")[:limit])
            parent_ids = {row.pk for row in parent_rows} | {parent_id for _, parent_id in profile_ids}
            locked_parents = list(Influencer.objects.select_for_update().filter(tenant_id=tenant_id, pk__in=parent_ids).order_by("pk"))
            parents = [row for row in locked_parents if row.canonical_handle_digest is None and row.pk in {item.pk for item in parent_rows}]
            profiles = list(InfluencerProfile.objects.select_for_update().filter(
                tenant_id=tenant_id, pk__in=[pk for pk, _ in profile_ids], canonical_external_id_digest__isnull=True,
            ).order_by("pk"))
            if any(row.influencer_id not in {item.pk for item in locked_parents} for row in profiles):
                raise CommandError("Cross-tenant profile detected; no writes applied")
            for row in parents:
                row.canonical_handle_digest = identity_digest(normalize_tiktok_username(row.handle))
            for row in profiles:
                row.canonical_external_id_digest = identity_digest(str(row.external_influencer_id or "").strip())
            if options["apply"]:
                # Bypass only the protected write wrapper, updating derived fields alone.
                QuerySet.bulk_update(QuerySet(model=Influencer), parents, ["canonical_handle_digest"], batch_size=limit)
                QuerySet.bulk_update(QuerySet(model=InfluencerProfile), profiles, ["canonical_external_id_digest"], batch_size=limit)
            self.stdout.write(json.dumps({
                "applied": options["apply"], "parents": len(parents), "profiles": len(profiles),
                "remaining_parents": Influencer.objects.filter(tenant_id=tenant_id, canonical_handle_digest__isnull=True).count(),
                "remaining_profiles": InfluencerProfile.objects.filter(tenant_id=tenant_id, canonical_external_id_digest__isnull=True).count(),
            }))
