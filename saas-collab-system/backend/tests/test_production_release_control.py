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


def test_internal_health_probe_marks_the_request_as_https():
    script = _health_script()

    assert '"X-Forwarded-Proto":"https"' in script
