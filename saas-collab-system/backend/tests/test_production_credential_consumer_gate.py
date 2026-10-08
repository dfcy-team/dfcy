import os
import shutil
import subprocess
from pathlib import Path

import pytest


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
COMMON = SYSTEM_ROOT / "deploy/production-control/lib/production-common.sh"


@pytest.mark.skipif(os.name == "nt", reason="Bash behavior is exercised in Linux CI")
@pytest.mark.parametrize(
    ("topology", "configured", "expected"),
    [
        ("redis\nbackend\ncelery-credentials\n", "redis,backend", "redis,backend,celery-credentials"),
        ("redis\nbackend\n", "redis,backend", "redis,backend"),
        (
            "redis\nbackend\ncelery-credentials\n",
            "redis,celery-credentials,backend",
            "redis,celery-credentials,backend",
        ),
        (
            "redis\nbackend\ncelery-credentials\n",
            "redis,backend,celery-control",
            "redis,backend,celery-control,celery-credentials",
        ),
    ],
)
def test_required_services_tracks_topology_and_preserves_explicit_services(
    tmp_path, topology, configured, expected
):
    _run_service_resolution(tmp_path, topology, configured, expected)


@pytest.mark.skipif(os.name == "nt", reason="Bash behavior is exercised in Linux CI")
def test_required_services_fails_closed_when_compose_service_parsing_fails(tmp_path):
    result = _service_resolution_process(tmp_path, "", "redis,backend", fail=True)
    assert result.returncode != 0
    assert "cannot parse production Compose services" in result.stderr


def test_candidate_overlay_pins_credentials_worker_to_release_backend_digest():
    script = (SYSTEM_ROOT / "deploy/production-control/bin/production-deploy").read_text(
        encoding="utf-8"
    )
    assert 'if (( has_credentials )); then' in script
    assert "  celery-credentials:\n    image: ${PRODUCTION_BACKEND_IMAGE" in script
    for name in ("production-deploy", "production-health-check", "production-recovery", "production-rollback"):
        text = (SYSTEM_ROOT / "deploy/production-control/bin" / name).read_text(encoding="utf-8")
        assert "production_required_services" in text


def test_pilot_install_starts_credentials_consumer_defined_in_compose():
    application = SYSTEM_ROOT / "deploy/pilot/application"
    install_script = (application / "install-app.sh").read_text(encoding="utf-8")
    compose = (application / "docker-compose.pilot-app.yml").read_text(encoding="utf-8")

    assert "  celery-credentials:" in compose
    assert "--queues=credential-refresh" in compose
    assert (
        'up -d --wait --wait-timeout 180 backend celery celery-history celery-background celery-control '
        'celery-credentials celery-beat frontend'
    ) in install_script


@pytest.mark.skipif(os.name == "nt", reason="Bash behavior is exercised in Linux CI")
def test_background_consumer_is_required_when_present(tmp_path):
    _run_service_resolution(tmp_path, "redis\nbackend\ncelery-background\ncelery-credentials\n", "redis,backend",
                            "redis,backend,celery-credentials,celery-background")


def test_background_image_cannot_remain_at_old_release():
    script = (SYSTEM_ROOT / "deploy/production-control/bin/production-deploy").read_text(encoding="utf-8")
    assert 'if (( has_background )); then' in script
    assert "  celery-background:\n    image: ${PRODUCTION_BACKEND_IMAGE" in script


def _run_service_resolution(tmp_path, topology, configured, expected):
    result = _service_resolution_process(tmp_path, topology, configured)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def _service_resolution_process(tmp_path, topology, configured, fail=False):
    common_copy = tmp_path / "control/lib/production-common.sh"
    common_copy.parent.mkdir(parents=True)
    shutil.copyfile(COMMON, common_copy)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = compose ] && [ "$2" = config ] && [ "$3" = --services ]; then\n'
        + ("  exit 42\n" if fail else '  printf "%s" "$FAKE_SERVICES"\n  exit 0\n')
        + "fi\nexit 1\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; COMPOSE=(docker compose); production_required_services "$2"',
            "bash",
            str(common_copy),
            configured,
        ],
        env=os.environ | {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}", "FAKE_SERVICES": topology},
        text=True,
        capture_output=True,
    )
