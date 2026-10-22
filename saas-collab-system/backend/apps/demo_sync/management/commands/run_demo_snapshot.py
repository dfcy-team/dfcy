import json
import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.demo_sync.service import run_batch, SyncFailure
from apps.demo_sync.models import SnapshotBatch


class Command(BaseCommand):
    help = "Run one queued snapshot on the explicitly enabled intranet worker."

    def add_arguments(self, parser):
        parser.add_argument("--batch-id", required=True, type=uuid.UUID)

    def handle(self, *args, **options):
        try:
            batch = run_batch(options["batch_id"])
        except (SyncFailure, SnapshotBatch.DoesNotExist) as error:
            raise CommandError(getattr(error, "code", "BATCH_NOT_FOUND")) from None
        self.stdout.write(json.dumps({"id": str(batch.pk), "status": batch.status,
                                      "summary": batch.summary, "error_code": batch.error_code}))
        if batch.status == "failed":
            raise CommandError(batch.error_code)
