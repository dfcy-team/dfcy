"""Regression checks for private, shared report-export storage in production."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_production_report_exports_use_one_private_persistent_volume():
    compose = yaml.safe_load(
        (ROOT / "deploy/production-control/production-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    backend_mounts = services["backend"]["volumes"]
    background_mounts = services["celery-background"]["volumes"]
    expected_mount = "production-report-exports:/app/media/report_exports"

    assert expected_mount in backend_mounts
    assert expected_mount in background_mounts
    assert compose["volumes"]["production-report-exports"]["name"] == "saas-production-report-exports"

    secret_targets = (
        "/run/secrets/openai-api.key:ro",
        "/run/secrets/pilot-runner.token:ro",
        "/run/secrets/pilot-runner-ca.pem:ro",
        "/run/secrets/custody-service.token:ro",
        "/run/secrets/custody-ca.pem:ro",
    )
    for target in secret_targets:
        assert any(mount.endswith(target) for mount in background_mounts)

    for service_name, service in services.items():
        if service_name not in {"backend", "celery-background"}:
            assert not any("/app/media/report_exports" in str(mount) for mount in service.get("volumes", []))
