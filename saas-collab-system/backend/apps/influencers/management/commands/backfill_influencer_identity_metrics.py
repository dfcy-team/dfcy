import csv
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.influencers.models import Influencer, InfluencerProfile
from apps.tenants.models import Tenant


def normalize_handle(value):
    return str(value or "").strip().lstrip("@").casefold()


def numeric_creator_id(value):
    value = str(value or "").strip()
    return value if value.isdigit() and value != "0" else ""


class Command(BaseCommand):
    help = "Backfill real creator IDs and follower counts from trusted legacy exports."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--profiles-csv", type=Path)
        parser.add_argument("--videos-csv", type=Path)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(pk=options["tenant_id"]).first()
        if tenant is None:
            raise CommandError("Tenant does not exist")
        if not options["profiles_csv"] and not options["videos_csv"]:
            raise CommandError("At least one source CSV is required")

        identities = defaultdict(set)
        followers = defaultdict(set)
        profile_path = options["profiles_csv"]
        if profile_path:
            self._read_profiles(profile_path, identities, followers)
        video_path = options["videos_csv"]
        if video_path:
            self._read_videos(video_path, identities)

        summary = {
            "mode": "apply" if options["apply"] else "dry-run",
            "identity_updates": 0,
            "follower_updates": 0,
            "ambiguous_identities": sum(len(values) > 1 for values in identities.values()),
            "ambiguous_followers": sum(len(values) > 1 for values in followers.values()),
        }
        with transaction.atomic():
            profiles = InfluencerProfile.objects.filter(tenant=tenant).select_related("influencer")
            for profile in profiles.iterator(chunk_size=1000):
                influencer = profile.influencer
                handle = normalize_handle(influencer.handle)
                creator_ids = identities.get(handle, set())
                if len(creator_ids) == 1 and not numeric_creator_id(profile.external_influencer_id):
                    summary["identity_updates"] += 1
                    if options["apply"]:
                        profile.external_influencer_id = next(iter(creator_ids))
                        profile.save(update_fields=["external_influencer_id", "updated_at"])
                follower_values = followers.get(handle, set())
                if len(follower_values) == 1 and influencer.follower_count == 0:
                    summary["follower_updates"] += 1
                    if options["apply"]:
                        influencer.follower_count = next(iter(follower_values))
                        influencer.save(update_fields=["follower_count", "updated_at"])
            if not options["apply"]:
                transaction.set_rollback(True)
        self.stdout.write(str(summary))

    @staticmethod
    def _rows(path):
        path = Path(path)
        if not path.is_file():
            raise CommandError(f"CSV file does not exist: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)

    def _read_profiles(self, path, identities, followers):
        for row in self._rows(path):
            handle = normalize_handle(row.get("normalized_handle") or row.get("handle"))
            creator_id = numeric_creator_id(row.get("creator_id"))
            if handle and creator_id:
                identities[handle].add(creator_id)
            try:
                follower_count = int(row.get("follower_count") or 0)
            except (TypeError, ValueError):
                continue
            if handle and follower_count > 0:
                followers[handle].add(follower_count)

    def _read_videos(self, path, identities):
        for row in self._rows(path):
            handle = normalize_handle(row.get("creator_name"))
            creator_id = numeric_creator_id(row.get("creator_id"))
            if handle and creator_id:
                identities[handle].add(creator_id)
