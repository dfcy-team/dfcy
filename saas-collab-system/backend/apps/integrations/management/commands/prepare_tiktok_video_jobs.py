"""Idempotent preparation only: never enqueue a run or enable a timer."""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError as ModelValidationError
from rest_framework.exceptions import APIException

from apps.masterdata.models import StoreMaster
from apps.integrations.video_jobs import prepare_video_job


class Command(BaseCommand):
    help = "Prepare one disabled video sync job per eligible TikTok shop (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--store-id", type=int, action="append")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["actor_id"],
            tenant_id=options["tenant_id"], is_active=True).first()
        if actor is None:
            raise CommandError("Active tenant-owned actor required.")
        stores = StoreMaster.objects.filter(tenant_id=actor.tenant_id,
            platform__platform_type="tiktok").order_by("pk")
        if options["store_id"]:
            stores = stores.filter(pk__in=options["store_id"])
            if stores.count() != len(set(options["store_id"])):
                raise CommandError("Requested shop is not a TikTok shop in this tenant.")
        counts = {}
        for store_id in stores.values_list("pk", flat=True):
            try:
                row = prepare_video_job(actor=actor, store_id=store_id, commit=options["commit"])
            except (APIException, ModelValidationError) as exc:
                # Do not emit provider configuration, credentials or arbitrary exception text.
                row = {"store_id": store_id, "action": "blocked", "error_type": type(exc).__name__}
            counts[row["action"]] = counts.get(row["action"], 0) + 1
            self.stdout.write(json.dumps(row))
        self.stdout.write(json.dumps({"summary": counts, "collection_started": False}))
