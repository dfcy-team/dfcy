from pathlib import Path


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
    script = _deploy_script()
    assert "PRODUCTION_IMAGE_PULL_TIMEOUT_SECONDS:-900" in script
    assert 'timeout --foreground --signal=TERM --kill-after=30s "${image_pull_timeout_seconds}s"' in script
    assert 'docker pull "$image" >"$pull_log" 2>&1' in script
    assert "failure_class=registry_auth" in script
    assert "failure_class=host_storage" in script
    assert "failure_class=registry_network" in script
    assert "failure_class=docker_daemon" in script
    assert 'die "$role image pull failed (class=$failure_class, exit=$pull_status, vm_log=$pull_log)."' in script
    assert 'docker pull "$backend_image" >/dev/null 2>&1' not in script


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
