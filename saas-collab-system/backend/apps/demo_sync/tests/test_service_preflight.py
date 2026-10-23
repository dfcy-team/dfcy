import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings


class DemoSyncServicePreflightTests(SimpleTestCase):
    def test_artifact_inside_static_root_is_rejected(self):
        from pathlib import Path
        from apps.demo_sync.management.commands.check_demo_sync_service import _artifact_directory, PreflightFailure
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifacts = root / "static" / "private"
            artifacts.mkdir(parents=True)
            with override_settings(DEMO_DATA_SYNC_ARTIFACT_ROOT=str(artifacts),
                                   STATIC_ROOT=str(root / "static"), MEDIA_ROOT=str(root / "media")):
                with self.assertRaisesMessage(PreflightFailure, "ARTIFACT_ROOT_INSIDE_STATIC"):
                    _artifact_directory()

    def test_disabled_role_is_rejected_before_database_or_network(self):
        with override_settings(DEMO_DATA_SYNC_SERVICE_INSTANCE=False,
                               DEMO_DATA_SYNC_ENABLED=True,
                               DEMO_DATA_SYNC_WORKER_ENABLED=True), \
                patch("apps.demo_sync.management.commands.check_demo_sync_service.connection") as db, \
                patch("apps.demo_sync.management.commands.check_demo_sync_service.ReadonlyClient") as client:
            output = self._run_failure()
        self.assertEqual(output["failures"], ["INTRANET_SERVICE_ROLE_REQUIRED"])
        db.assert_not_called()
        db.cursor.assert_not_called()
        client.assert_not_called()

    def test_default_disabled_flags_fail_before_database(self):
        with override_settings(DEMO_DATA_SYNC_SERVICE_INSTANCE=True,
                               DEMO_DATA_SYNC_ENABLED=False,
                               DEMO_DATA_SYNC_WORKER_ENABLED=False,
                               DEMO_DATA_SYNC_IMPORT_ENABLED=False), \
                patch("apps.demo_sync.management.commands.check_demo_sync_service.connection") as db:
            output = self._run_failure()
        self.assertEqual(output["failures"], ["WORKER_DISABLED"])
        db.assert_not_called()
        db.cursor.assert_not_called()

    @override_settings(DEMO_DATA_SYNC_SERVICE_INSTANCE=True,
                       DEMO_DATA_SYNC_ENABLED=False,
                       DEMO_DATA_SYNC_WORKER_ENABLED=False,
                       DEMO_DATA_SYNC_IMPORT_ENABLED=False)
    def test_allow_disabled_checks_prepared_role_without_starting_work(self):
        with tempfile.TemporaryDirectory() as artifact_root, tempfile.TemporaryDirectory() as media_root:
            source = {"default": {"url": "https://sync.example.test", "tenant_id": 23,
                      "client_id_env": "PREFLIGHT_CLIENT", "client_secret_env": "PREFLIGHT_SECRET",
                      "masking_key_env": "PREFLIGHT_MASK"}}
            fake_db = _FakeConnection()
            fake_executor = MagicMock()
            fake_executor.loader.graph.leaf_nodes.return_value = []
            fake_executor.migration_plan.return_value = []
            session = MagicMock()
            with override_settings(DEMO_DATA_SYNC_ARTIFACT_ROOT=artifact_root,
                                   MEDIA_ROOT=media_root,
                                   DEMO_DATA_SYNC_ALLOWED_HOSTS=["sync.example.test"],
                                   DEMO_DATA_SYNC_SOURCES=source), \
                    patch.dict(os.environ, {"PREFLIGHT_CLIENT": "id", "PREFLIGHT_SECRET": "secret",
                                            "PREFLIGHT_MASK": "m" * 32}), \
                    patch("apps.demo_sync.management.commands.check_demo_sync_service.connection", fake_db), \
                    patch("apps.demo_sync.management.commands.check_demo_sync_service.MigrationExecutor",
                          return_value=fake_executor), \
                    patch("apps.demo_sync.management.commands.check_demo_sync_service._artifact_directory",
                          return_value=artifact_root), \
                    patch("apps.demo_sync.service.requests.Session", return_value=session):
                output = self._run_success("--allow-disabled")
        self.assertTrue(output["ok"])
        self.assertEqual(output["checks"]["feature_flags"], "prepare_only")
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT")
                            for sql, _params in fake_db.sql))
        session.get.assert_not_called()
        session.close.assert_called_once()

    def test_failures_are_stable_and_do_not_echo_source_values(self):
        with override_settings(DEMO_DATA_SYNC_SERVICE_INSTANCE=True,
                               DEMO_DATA_SYNC_ENABLED=True,
                               DEMO_DATA_SYNC_WORKER_ENABLED=True,
                               DEMO_DATA_SYNC_IMPORT_ENABLED=True):
            output = self._run_failure()
        self.assertEqual(output["failures"], ["IMPORT_MUST_REMAIN_DISABLED"])
        self.assertNotIn("https://", json.dumps(output))
        self.assertNotIn("secret", json.dumps(output))

    def _run_failure(self, *args):
        from io import StringIO
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("check_demo_sync_service", *args, stdout=output)
        return json.loads(output.getvalue())

    def _run_success(self, *args):
        from io import StringIO
        output = StringIO()
        call_command("check_demo_sync_service", *args, stdout=output)
        return json.loads(output.getvalue())


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.connection.sql.append((sql, params))
        self.result = ("saas_collab_sync_preflight",) if "DATABASE()" in sql else (23,)

    def fetchone(self):
        return self.result


class _FakeConnection:
    vendor = "mysql"

    def __init__(self):
        self.sql = []
        self.ops = SimpleNamespace(quote_name=lambda value: f"`{value}`")

    def cursor(self):
        return _FakeCursor(self)
