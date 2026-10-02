"""Static regression checks for credential refresh worker isolation."""
import ast
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def service_block(compose_text, name):
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w.-]+:\n|^networks:|\Z)", compose_text)
    if not match:
        raise AssertionError(f"service {name!r} is missing")
    return match.group(1)


class CredentialQueueIsolationTests(unittest.TestCase):
    def test_refresh_scan_has_a_bounded_budget_and_preserves_feishu_budget(self):
        tree = ast.parse((ROOT / "backend/apps/integrations/tasks.py").read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        decorator = functions["refresh_due_integration_credentials"].decorator_list[0]
        self.assertIsInstance(decorator, ast.Call)
        self.assertEqual({item.arg: ast.literal_eval(item.value) for item in decorator.keywords},
                         {"soft_time_limit": 540, "time_limit": 600})
        original_budget = functions["dispatch_feishu_deliveries"].decorator_list[0]
        self.assertEqual({item.arg: ast.literal_eval(item.value) for item in original_budget.keywords},
                         {"soft_time_limit": 540, "time_limit": 600})

    def test_settings_route_and_bounded_beat_scan(self):
        source = (ROOT / "backend/config/settings/base.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"CELERY_TASK_ROUTES", "CELERY_BROKER_TRANSPORT_OPTIONS"}
        }
        self.assertEqual(
            assignments["CELERY_TASK_ROUTES"]["apps.integrations.tasks.refresh_due_integration_credentials"],
            {"queue": "credential-refresh"},
        )
        self.assertEqual(assignments["CELERY_BROKER_TRANSPORT_OPTIONS"]["queue_order_strategy"], "round_robin")
        beat = re.search(r'(?ms)^    "refresh-due-integration-credentials": \{(.*?)^    \},', source)
        self.assertIsNotNone(beat)
        self.assertIn('"schedule": 60.0', beat.group(1))
        self.assertIn('"queue": "credential-refresh"', beat.group(1))
        self.assertIn('"expires": 55', beat.group(1))

    def test_production_worker_reuses_runtime_custody_and_network(self):
        source = (ROOT / "deploy/production-control/production-compose.yml").read_text(encoding="utf-8")
        business = service_block(source, "celery")
        credentials = service_block(source, "celery-credentials")
        for expected in (
            "PRODUCTION_BACKEND_IMAGE", "PRODUCTION_RUNTIME_ENV_FILE", "PRODUCTION_OPENAI_API_KEY_PATH",
            "PRODUCTION_RUNNER_TOKEN_PATH", "PRODUCTION_CUSTODY_SERVICE_TOKEN_PATH",
            "production-internal", "custody-sidecar", "extra_hosts", "credential-refresh",
            "--concurrency=1", "--prefetch-multiplier=1", "--hostname=credentials@%h",
        ):
            self.assertIn(expected, credentials)
        self.assertIn("LIVE_CUSTODY_SERVICE_URL", credentials)
        self.assertNotIn("--queues=sync", credentials)
        self.assertIn("PRODUCTION_BACKEND_IMAGE", business)

    def test_pilot_and_dev_topologies_have_isolated_consumer(self):
        pilot = (ROOT / "deploy/pilot/application/docker-compose.pilot-app.yml").read_text(encoding="utf-8")
        dev = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for source, image, envfile, volume, network in (
            (pilot, "PILOT_BACKEND_IMAGE", "PILOT_ENV_FILE", "PILOT_RUNNER_TOKEN_PATH", "pilot-internal"),
            (dev, "context: ./backend", "DJANGO_SETTINGS_MODULE", "./backend:/app", "condition: service_started"),
        ):
            worker = service_block(source, "celery-credentials")
            for expected in (image, envfile, volume, "credential-refresh", "--concurrency=1", "--prefetch-multiplier=1"):
                self.assertIn(expected, worker)
        dev_business = service_block(dev, "celery")
        self.assertIn("--queues=sync,celery", dev_business)
        self.assertNotIn("credential-refresh", dev_business)


if __name__ == "__main__":
    unittest.main()
