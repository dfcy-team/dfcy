"""Opt-in polling worker for the intranet demo snapshot queue."""
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from apps.demo_sync.contracts import enabled
from apps.demo_sync.models import SnapshotBatch
from apps.demo_sync.service import SyncFailure, run_batch


MIN_POLL_SECONDS = 1
MAX_POLL_SECONDS = 300


class Command(BaseCommand):
    help = "Poll and run queued snapshots on an explicitly enabled intranet service."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one queued snapshot, then exit.")
        parser.add_argument("--poll-seconds", type=float, default=5,
                            help="Idle polling interval (1 to 300 seconds; default: 5).")

    @staticmethod
    def _check_gates():
        # Keep these checks ahead of every queue query. The service repeats the
        # same safety gates when it claims a task.
        if not enabled() or not getattr(settings, "DEMO_DATA_SYNC_WORKER_ENABLED", False):
            raise CommandError("WORKER_DISABLED")
        if not getattr(settings, "DEMO_DATA_SYNC_SERVICE_INSTANCE", False):
            raise CommandError("INTRANET_SERVICE_ROLE_REQUIRED")

    def handle(self, *args, **options):
        poll_seconds = options["poll_seconds"]
        if not MIN_POLL_SECONDS <= poll_seconds <= MAX_POLL_SECONDS:
            raise CommandError("--poll-seconds must be between 1 and 300")

        once = options["once"]
        try:
            while True:
                self._check_gates()
                close_old_connections()
                try:
                    batch_id = (SnapshotBatch.objects.filter(status=SnapshotBatch.Status.QUEUED)
                                .order_by("created_at", "pk").values_list("pk", flat=True).first())
                    if batch_id is None:
                        if once:
                            return
                    else:
                        try:
                            batch = run_batch(batch_id)
                        except SyncFailure as error:
                            if error.code != "BATCH_NOT_QUEUED":
                                raise CommandError(error.code) from None
                            # Another worker claimed it after our query. This is
                            # a normal race; queued-only selection avoids retries.
                            if once:
                                return
                            continue
                        self.stdout.write(f"snapshot {batch.pk}: {batch.status}")
                        if once:
                            return
                finally:
                    close_old_connections()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            self.stdout.write("Snapshot worker stopped.")
