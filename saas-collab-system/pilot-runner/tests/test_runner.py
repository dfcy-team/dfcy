from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pilot_runner_app", ROOT / "app.py")
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


class RunnerTests(unittest.TestCase):
    def make_service(self, *, command=None, max_concurrent=2):
        self.tempdir = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tempdir.name)
        token_file = root / "runner.token"
        token_file.write_text("runner-test-token\n", encoding="utf-8")
        token_file.chmod(0o600)
        candidate_file = root / "approved-candidate.json"
        candidate_file.write_text(
            json.dumps(
                {
                    "release_version": "2.44.59",
                    "parent_release": "2.44.58",
                    "release_sha": "a" * 40,
                    "parent_release_sha": "b" * 40,
                    "release_plan": {"version": "2.44.59", "ref": "release/system-v2.44.59"},
                }
            ),
            encoding="utf-8",
        )
        candidate_file.chmod(0o600)
        command = command or [sys.executable, "-c", "print('fixed-command-ok')"]
        data = {
            "schema_version": 1,
            "listen": {"host": "127.0.0.1", "port": 19444},
            "auth": {"token_file": str(token_file)},
            "paths": {
                "state_file": str(root / "state" / "state.sqlite3"),
                "audit_file": str(root / "audit" / "audit.jsonl"),
                "evidence_dir": str(root / "evidence"),
                "candidate_manifest_file": str(candidate_file),
            },
            "limits": {
                "max_body_bytes": 4096,
                "max_concurrent": max_concurrent,
                "max_operation_timeout_seconds": 10,
                "max_performance_rps": 2,
                "max_performance_concurrency": 2,
                "max_performance_duration_seconds": 2,
            },
            "environments": {
                "controlled-pilot": {
                    "operations": {
                        "deploy": {"argv": command, "timeout_seconds": 5},
                        "recovery": {"argv": command, "timeout_seconds": 5},
                        "rollback": {"argv": command, "timeout_seconds": 5},
                        "performance": {
                            "mode": "http",
                            "timeout_seconds": 5,
                            "targets": {"health": "https://backend.example.test/healthz"},
                            "profiles": {
                                "smoke": {
                                    "target": "health",
                                    "rps": 1,
                                    "concurrency": 1,
                                    "duration_seconds": 1,
                                    "request_timeout_seconds": 1,
                                    "method": "GET",
                                }
                            },
                        },
                    }
                }
            },
        }
        service = app.RunnerService(app.RunnerConfig(data))
        self.addCleanup(self.tempdir.cleanup)
        self.addCleanup(service.close)
        return service, root

    def wait_for_terminal(self, service, operation_id):
        for _ in range(100):
            result = service.get_result(operation_id)
            if result["status"] in {"succeeded", "failed", "timed_out", "rejected", "interrupted"}:
                return result
            time.sleep(0.01)
        self.fail("operation did not reach a terminal state")

    def test_token_file_authentication_uses_digest_and_never_requires_env(self):
        service, _ = self.make_service()
        self.assertTrue(service.authenticate("Bearer runner-test-token"))
        self.assertFalse(service.authenticate("Bearer wrong-token"))
        self.assertFalse(service.authenticate("runner-test-token"))
        self.assertFalse(hasattr(service, "token"))

    def test_fixed_argv_is_idempotent_and_conflicts_on_payload_change(self):
        service, root = self.make_service()
        status, accepted = service.submit(
            {
                "environment": "controlled-pilot",
                "operation": "deploy",
                "expected_release_sha": "a" * 40,
                "release_plan_ref": "release/system-v2.44.59",
            },
            "deploy-key-1",
        )
        self.assertEqual(status, 202)
        result = self.wait_for_terminal(service, accepted["operation_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["started_at"])
        self.assertTrue(result["deadline_at"])
        self.assertGreater(result["deadline_at"], result["started_at"])
        self.assertEqual(result["target_release_sha"], "a" * 40)
        self.assertEqual(result["target_release_version"], "2.44.59")
        self.assertEqual(result["target_release_plan_ref"], "release/system-v2.44.59")
        self.assertTrue(result["evidence_ref"].startswith("evidence/"))
        evidence = root / "evidence" / f"{accepted['operation_id']}.json"
        self.assertIn("fixed-command-ok", evidence.read_text(encoding="utf-8"))
        replay_status, replay = service.submit(
            {
                "environment": "controlled-pilot",
                "operation": "deploy",
                "expected_release_sha": "a" * 40,
                "release_plan_ref": "release/system-v2.44.59",
            },
            "deploy-key-1",
        )
        self.assertEqual(replay_status, 200)
        self.assertEqual(replay["operation_id"], accepted["operation_id"])
        with self.assertRaises(app.RunnerError) as raised:
            service.submit({"environment": "controlled-pilot", "operation": "rollback"}, "deploy-key-1")
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_operation_rejects_client_parameters_and_unknown_targets(self):
        service, _ = self.make_service()
        with self.assertRaises(app.RunnerError):
            service.submit({"environment": "controlled-pilot", "operation": "deploy", "argv": ["/bin/sh"]}, "bad-key-1")
        with self.assertRaises(app.RunnerError) as raised:
            service.submit({"environment": "controlled-pilot", "operation": "performance", "profile": "smoke", "target_alias": "https://attacker.invalid"}, "bad-key-2")
        self.assertEqual(raised.exception.code, "TARGET_NOT_ALLOWLISTED")

    def test_performance_metrics_are_server_profile_driven(self):
        service, _ = self.make_service()

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"ok"

        with mock.patch.object(app.urllib.request, "urlopen", return_value=Response()), mock.patch.object(
            app, "_host_cpu_counters", side_effect=[(100, 50), (200, 100)]
        ), mock.patch.object(app, "_host_memory_percent", return_value=40.0):
            status, accepted = service.submit({"environment": "controlled-pilot", "operation": "performance", "profile": "smoke"}, "perf-key-1")
            self.assertEqual(status, 202)
            result = self.wait_for_terminal(service, accepted["operation_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["metrics"]["error_rate"], 0.0)
        self.assertIn("p50_ms", result["metrics"])
        self.assertIn("p95_ms", result["metrics"])
        self.assertEqual(result["metrics"]["cpu_percent"], 50.0)
        self.assertEqual(result["metrics"]["memory_percent"], 40.0)
        self.assertEqual(result["metrics"]["metrics_source"], "app-vm-host-proc")
        self.assertEqual(result["metrics"]["scope"], "app_vm_host")

    def test_http_performance_fails_closed_without_host_resource_metrics(self):
        service, _ = self.make_service()

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"ok"

        with mock.patch.object(app.urllib.request, "urlopen", return_value=Response()), mock.patch.object(
            app, "_host_cpu_counters", return_value=None
        ), mock.patch.object(app, "_host_memory_percent", return_value=None):
            status, accepted = service.submit({"environment": "controlled-pilot", "operation": "performance", "profile": "smoke"}, "perf-key-2")
            self.assertEqual(status, 202)
            result = self.wait_for_terminal(service, accepted["operation_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["metrics"]["cpu_percent"])
        self.assertIsNone(result["metrics"]["memory_percent"])
        self.assertEqual(result["error_code"], "PERFORMANCE_RESOURCE_METRICS_UNAVAILABLE")

    def test_deploy_requires_exact_approved_release_binding(self):
        service, _ = self.make_service()
        with self.assertRaises(app.RunnerError) as raised:
            service.submit(
                {
                    "environment": "controlled-pilot",
                    "operation": "deploy",
                    "expected_release_sha": "c" * 40,
                    "release_plan_ref": "release/system-v2.44.59",
                },
                "deploy-key-mismatch",
            )
        self.assertEqual(raised.exception.code, "RELEASE_BINDING_MISMATCH")

    def test_recovery_success_returns_reconciliation_rpo_rto_metrics(self):
        service, _ = self.make_service()
        status, accepted = service.submit({"environment": "controlled-pilot", "operation": "recovery"}, "recovery-key-1")
        self.assertEqual(status, 202)
        result = self.wait_for_terminal(service, accepted["operation_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["metrics"]["actual_rpo_minutes"], 0)
        self.assertGreaterEqual(result["metrics"]["actual_rto_minutes"], 0)
        self.assertEqual(result["metrics"]["scope"], "application_service_reconciliation")

    def test_low_rps_scheduler_waits_until_deadline_in_bounded_slices(self):
        now = [0.0]
        sleeps = []

        def clock():
            return now[0]

        def sleeper(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        app._sleep_until(0.65, clock=clock, sleeper=sleeper)
        self.assertEqual(len(sleeps), 4)
        for actual, expected in zip(sleeps, [0.2, 0.2, 0.2, 0.05]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertGreaterEqual(now[0], 0.65)

    def test_config_rejects_plaintext_performance_target(self):
        service, _ = self.make_service()
        data = service.config._data
        data["environments"]["controlled-pilot"]["operations"]["performance"]["targets"]["health"] = "http://backend.example.test/healthz"
        with self.assertRaises(app.RunnerError) as raised:
            app.RunnerConfig(data)
        self.assertEqual(raised.exception.code, "CONFIG_INVALID")

    def test_config_rejects_performance_profile_that_exceeds_operation_deadline(self):
        service, _ = self.make_service()
        data = service.config._data
        performance = data["environments"]["controlled-pilot"]["operations"]["performance"]
        performance["timeout_seconds"] = 5
        performance["profiles"]["smoke"]["duration_seconds"] = 5
        performance["profiles"]["smoke"]["request_timeout_seconds"] = 1
        with self.assertRaises(app.RunnerError) as raised:
            app.RunnerConfig(data)
        self.assertEqual(raised.exception.code, "CONFIG_INVALID")

    def test_source_has_no_shell_execution_path(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertIn("shell=False", source)


if __name__ == "__main__":
    unittest.main()
