import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _deploy_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (
        system_root / "deploy" / "production-control" / "bin" / "production-deploy"
    ).read_text(encoding="utf-8")


def _install_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (
        system_root / "deploy" / "production-control" / "bin" / "install-control.sh"
    ).read_text(encoding="utf-8")


def _production_workflow() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / ".github" / "workflows" / "developer-a-production-release.yml").read_text(
        encoding="utf-8"
    )


def _health_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (
        system_root / "deploy" / "production-control" / "bin" / "production-health-check"
    ).read_text(encoding="utf-8")


def _common_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (system_root / "deploy" / "production-control" / "lib" / "production-common.sh").read_text(encoding="utf-8")


def _rollback_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (
        system_root / "deploy" / "production-control" / "bin" / "production-rollback"
    ).read_text(encoding="utf-8")


def _recovery_script() -> str:
    system_root = Path(__file__).resolve().parents[2]
    return (
        system_root / "deploy" / "production-control" / "bin" / "production-recovery"
    ).read_text(encoding="utf-8")


def test_cli_digests_are_exported_before_compose_initialization():
    script = _deploy_script()
    validation = script.index(
        'validate_approved_images "$backend_image" "$frontend_image" "$redis_image"'
    )
    exports = [
        script.index('export PRODUCTION_BACKEND_IMAGE="$backend_image"'),
        script.index('export PRODUCTION_FRONTEND_IMAGE="$frontend_image"'),
        script.index('export PRODUCTION_REDIS_IMAGE="$redis_image"'),
    ]
    load_env = script.index("\nload_production_env\n", max(exports))
    init_compose = script.index("\ninit_compose\n", load_env)

    assert validation < min(exports)
    assert max(exports) < load_env < init_compose


def test_candidate_overlay_is_last_and_restores_full_migration_command():
    script = _deploy_script()
    init_compose = script.index("init_compose")
    create_overlay = script.index("create_candidate_compose_overlay", init_compose)
    compose_validation = script.index('"${COMPOSE[@]}" config --quiet')
    overlay = script[
        script.index("cat > \"$candidate_compose_overlay\" <<'EOF'") : script.index(
            "\nEOF", script.index("cat > \"$candidate_compose_overlay\" <<'EOF'")
        )
    ]

    assert init_compose < create_overlay < compose_validation
    assert overlay.count("${PRODUCTION_BACKEND_IMAGE") == 4
    assert overlay.count("${PRODUCTION_FRONTEND_IMAGE") == 1
    assert overlay.count("${PRODUCTION_REDIS_IMAGE") == 1
    assert "- migrate\n      - --noinput" in overlay
    assert '- --verbosity\n      - "2"' in overlay


def test_database_migration_has_bounded_runtime_and_visible_output():
    script = _deploy_script()

    assert "require_command timeout" in script
    assert "PRODUCTION_MIGRATION_TIMEOUT_SECONDS:-1200" in script
    assert "timeout --foreground --signal=TERM --kill-after=30s" in script
    assert 'run --rm --name "$migration_container" "$migration_service"' in script
    assert 'docker rm -f "$migration_container"' in script
    assert 'run --rm "$migration_service" >/dev/null' not in script


def test_image_pull_is_bounded_and_failure_is_classified_without_printing_raw_log():
    common = _common_script()
    deploy = _deploy_script()
    rollback = _rollback_script()
    assert "PRODUCTION_IMAGE_PULL_TIMEOUT_SECONDS:-900" in common
    assert 'timeout --foreground --signal=TERM --kill-after=30s "${image_pull_timeout_seconds}s"' in common
    assert 'docker pull "$image" >"$pull_log" 2>&1' in common
    assert "failure_class=registry_auth" in common
    assert "failure_class=host_storage" in common
    assert "failure_class=registry_network" in common
    assert "failure_class=docker_daemon" in common
    assert '"$role" "$failure_class" "$pull_status" "$pull_log" >&2' in common
    assert 'configure_image_pull_timeout' in deploy
    assert 'configure_image_pull_timeout' in rollback
    assert 'ensure_rollback_image backend "$old_backend" || return 1' in deploy
    assert 'ensure_rollback_image backend "$target_backend" || die' in rollback
    assert 'docker pull "$old_backend"' not in deploy
    assert 'docker pull "$target_backend"' not in rollback


def test_production_compose_never_builds_from_mutable_vm_source():
    for script in (_deploy_script(), _rollback_script(), _recovery_script()):
        up_calls = [line for line in script.splitlines() if '"${COMPOSE[@]}" up ' in line]
        assert up_calls
        assert all('up --no-build ' in line for line in up_calls)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell behavior is exercised in Linux CI")
@pytest.mark.parametrize("cached", [False, True])
def test_rollback_uses_cached_image_or_bounded_pull_without_leaking_raw_log(tmp_path, cached):
    common_copy = tmp_path / "control" / "lib" / "production-common.sh"
    common_copy.parent.mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[2]
        / "deploy" / "production-control" / "lib" / "production-common.sh",
        common_copy,
    )
    (common_copy.parent.parent / "ledger").mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = image ] && [ "$2" = inspect ]; then\n'
        '  [ "$FAKE_CACHED" = 1 ]; exit $?\n'
        'fi\n'
        'printf "TLS handshake timeout; private diagnostic\\n" >&2\n'
        'exit 1\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    timeout = fake_bin / "timeout"
    timeout.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$*" > "$TIMEOUT_TRACE"\n'
        'shift 4\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    timeout.chmod(0o755)
    trace = tmp_path / "timeout.trace"
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CACHED": "1" if cached else "0",
        "TIMEOUT_TRACE": str(trace),
        "PRODUCTION_IMAGE_PULL_TIMEOUT_SECONDS": "60",
    }
    result = subprocess.run(
        [
            "bash", "-c",
            'source "$1"; configure_image_pull_timeout; '
            'if ensure_rollback_image backend "$2"; then echo READY; else echo FAILED; fi',
            "bash", str(common_copy), "ghcr.io/example/backend@sha256:" + "a" * 64,
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    if cached:
        assert "READY" in result.stdout
        assert not trace.exists()
        assert not list((common_copy.parent.parent / "ledger").iterdir())
    else:
        assert "FAILED" in result.stdout
        assert "class=registry_network" in result.stderr
        assert "private diagnostic" not in result.stdout + result.stderr
        assert "--kill-after=30s 60s docker pull" in trace.read_text(encoding="utf-8")
        logs = list((common_copy.parent.parent / "ledger").iterdir())
        assert len(logs) == 1
        assert logs[0].stat().st_mode & 0o777 == 0o600
        assert "private diagnostic" in logs[0].read_text(encoding="utf-8")


def test_registry_login_has_timeout_without_logging_token():
    script = _common_script()
    assert 'timeout --foreground --signal=TERM --kill-after=10s 90s' in script
    assert "GHCR authentication timed out after 90 seconds" in script
    assert 'printf \'%s\' "$token"' in script


def test_baseline_tracks_control_environment_and_its_compose_override():
    script = _install_script()
    control_env = script.index('control_env="$CONTROL_ROOT/config/control.env"')
    control_hash = script.index('sha256sum "$control_env"', control_env)
    live_compose = script.index("compose_list=$(sed", control_hash)
    control_compose = script.index("control_compose_list=$(sed", live_compose)
    select_override = script.index("compose_list=$control_compose_list", control_compose)
    compose_hash = script.index('sha256sum "$compose_file"', select_override)

    assert control_env < control_hash < live_compose
    assert live_compose < control_compose < select_override < compose_hash


def test_production_release_builds_the_pilot_frontend_image():
    workflow = _production_workflow()

    assert "file: saas-collab-system/deploy/pilot/application/Dockerfile.frontend" in workflow
    assert "file: saas-collab-system/deploy/sandbox/application/Dockerfile.frontend" not in workflow


def test_registry_token_is_written_to_ssh_stdin_without_pipeline_newline():
    workflow = _production_workflow()

    assert "$env:GHCR_TOKEN | & ssh.exe" not in workflow
    assert workflow.count("$ssh.RedirectStandardInput = $true") == 2
    assert workflow.count("$process.StandardInput.Write($env:GHCR_TOKEN)") == 2


def test_internal_health_probe_marks_the_request_as_https():
    script = _health_script()

    assert '"X-Forwarded-Proto":"https"' in script
