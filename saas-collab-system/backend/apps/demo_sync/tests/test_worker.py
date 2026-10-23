from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from apps.demo_sync.models import SnapshotBatch, SyncEnvironment
from apps.demo_sync.service import SyncFailure
from apps.tenants.models import Tenant


class SnapshotQueueWorkerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(code="WORKER-A", name="Synthetic worker")
        self.user = get_user_model().objects.create_user(
            username="snapshot-worker-owner", tenant=self.tenant, user_type="internal"
        )
        self.environment = SyncEnvironment.objects.create(
            tenant=self.tenant, owner=self.user, name="Worker source", resources=["products"]
        )

    def queue(self):
        return SnapshotBatch.objects.create(
            tenant=self.tenant, environment=self.environment, requested_by=self.user,
            date_from=date(2026, 10, 1), date_to=date(2026, 10, 2),
        )

    def test_all_gates_are_checked_before_queue_query(self):
        cases = (
            {"DEMO_DATA_SYNC_ENABLED": False, "DEMO_DATA_SYNC_WORKER_ENABLED": True,
             "DEMO_DATA_SYNC_SERVICE_INSTANCE": True, "message": "WORKER_DISABLED"},
            {"DEMO_DATA_SYNC_ENABLED": True, "DEMO_DATA_SYNC_WORKER_ENABLED": False,
             "DEMO_DATA_SYNC_SERVICE_INSTANCE": True, "message": "WORKER_DISABLED"},
            {"DEMO_DATA_SYNC_ENABLED": True, "DEMO_DATA_SYNC_WORKER_ENABLED": True,
             "DEMO_DATA_SYNC_SERVICE_INSTANCE": False, "message": "INTRANET_SERVICE_ROLE_REQUIRED"},
        )
        for case in cases:
            settings = {key: value for key, value in case.items() if key != "message"}
            with self.subTest(settings=settings), override_settings(**settings), \
                    patch.object(SnapshotBatch.objects, "filter") as query:
                with self.assertRaisesMessage(CommandError, case["message"]):
                    call_command("work_demo_snapshots", once=True)
                query.assert_not_called()

    @override_settings(DEMO_DATA_SYNC_ENABLED=True, DEMO_DATA_SYNC_WORKER_ENABLED=True,
                       DEMO_DATA_SYNC_SERVICE_INSTANCE=True)
    def test_once_takes_oldest_queued_batch_and_runs_only_one(self):
        oldest = self.queue()
        self.queue()
        with patch("apps.demo_sync.management.commands.work_demo_snapshots.run_batch",
                   return_value=SimpleNamespace(pk=oldest.pk, status="ready")) as run:
            call_command("work_demo_snapshots", once=True)
        run.assert_called_once_with(oldest.pk)

    @override_settings(DEMO_DATA_SYNC_ENABLED=True, DEMO_DATA_SYNC_WORKER_ENABLED=True,
                       DEMO_DATA_SYNC_SERVICE_INSTANCE=True)
    def test_lost_claim_race_is_harmless_in_once_mode(self):
        batch = self.queue()
        with patch("apps.demo_sync.management.commands.work_demo_snapshots.run_batch",
                   side_effect=SyncFailure("BATCH_NOT_QUEUED")) as run:
            call_command("work_demo_snapshots", once=True)
        run.assert_called_once_with(batch.pk)

