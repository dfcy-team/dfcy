from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

def _bash_exe():
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(r"C:\Program Files\Git\bin\bash.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise AssertionError("Git Bash is required for isolated forced-command tests")
    executable = shutil.which("bash")
    assert executable, "bash is required for isolated forced-command tests"
    return executable

def _bash_path(path):
    path = str(path)
    if os.name != "nt":
        return path
    result = subprocess.run(
        [_bash_exe(), "-lc", 'cygpath -u "$1"', "path-convert", path],
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()

def _repo_root():
    return Path(__file__).resolve().parents[4]

def _control():
    return Path(__file__).resolve().parents[1]

def _run_ci_baseline(repo_root, env=None):
    return subprocess.run(
        [_bash_exe(), "-c", './saas-collab-system/deploy/production-control/bin/production-baseline-check --ci --repo-root "$PWD"'],
        cwd=str(repo_root), text=True, capture_output=True, timeout=60, env=env,
    )

def _minimal_repo_fixture(repo_root):
    source = _control()
    target = repo_root / "saas-collab-system" / "deploy" / "production-control"
    (target / "bin").mkdir(parents=True)
    (target / "lib").mkdir(parents=True)
    for name in ("README.md", "production-compose.yml", "env.production.example"):
        shutil.copyfile(source / name, target / name)
    shutil.copytree(source / "bin", target / "bin", dirs_exist_ok=True)
    shutil.copytree(source / "lib", target / "lib", dirs_exist_ok=True)
    workflows = repo_root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    shutil.copyfile(_repo_root() / ".github" / "workflows" / "developer-a-production-release.yml",
                    workflows / "developer-a-production-release.yml")
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True, capture_output=True)
    return target

def test_precache_action_uses_exact_artifact_and_secret_stdin():
    workflow = (_repo_root() / ".github/workflows/developer-a-production-release.yml").read_text()
    assert "precache-v316-attempt2" in workflow
    assert "run-id: 40515060731" in workflow
    assert "PRODUCTION_GHCR_PULL_TOKEN || github.token" in workflow
    assert "$env:GHCR_TOKEN | & ssh.exe" not in workflow
    assert "StandardInput.BaseStream.Write" in workflow
    assert "^[A-Za-z0-9._:-]+\\z" in workflow
    job = workflow[workflow.index("  precache-v316-attempt2:"):workflow.index("  remote-rollback:")]
    assert "needs.build" not in job and "needs: [validate, build]" not in job

def test_fixed_dispatcher_install_and_target_are_narrow():
    control = _control()
    dispatch = (control / "bin/developer-a-ci-dispatch").read_text()
    install = (control / "bin/install-control.sh").read_text()
    baseline = (control / "bin/production-baseline-check").read_text()
    target_path = control / "bin/production-image-precache-v316-attempt2"
    target = target_path.read_text()
    assert "precache-v316-attempt2)" in dispatch
    assert 'run_fixed "$PRECACHE_BIN" "${argv[@]}"' in dispatch
    assert target.startswith("#!/usr/bin/python3\n")
    assert "production-image-precache-v316-attempt2" in install
    assert "production-image-precache-v316-attempt2" in baseline
    assert "RUN=40515060731" in target and "'900s'" in target
    assert "def active_docker_pull()" in target and "post_readback" in target
    assert "remove_docker_config" in target and "105s" in target
    assert "docker compose" not in target.lower()
    assert "docker system prune" not in target.lower()

def test_real_production_common_cleans_auth_directory_after_login_failure():
    common = _control() / "lib/production-common.sh"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "control"
        lib = root / "lib"
        lib.mkdir(parents=True)
        shutil.copyfile(common, lib / "production-common.sh")
        (root / "bin").mkdir()
        docker_bin = Path(temp) / "mock-bin"
        docker_bin.mkdir()
        stub = docker_bin / "docker"
        stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(0o755)
        script = (
            'set -Eeuo pipefail; source "$1"; new_docker_config; '
            'cleanup_auth(){ local status=$?; trap - EXIT; remove_docker_config; exit "$status"; }; '
            'trap cleanup_auth EXIT; trap "exit 129" HUP; trap "exit 130" INT; '
            'trap "exit 143" TERM; docker_login_from_stdin "$2"; '
            'printf "%s\n" "$DOCKER_CONFIG"; trap - EXIT HUP INT TERM'
        )
        result = subprocess.run(
            [_bash_exe(), "-c", script, "precache-auth", _bash_path(lib / "production-common.sh"), "cache-test"],
            input="fake-test-token", text=True, capture_output=True,
            env=dict(os.environ, PATH=_bash_path(docker_bin) + (":" if os.name == "nt" else os.pathsep) + ("/usr/bin:/bin" if os.name == "nt" else os.environ.get("PATH", ""))),
            timeout=15,
        )
        assert result.returncode != 0
        assert "fake-test-token" not in result.stdout + result.stderr
        assert list(root.glob(".docker-config.*")) == []

def test_real_dispatcher_accepts_only_exact_fixed_arguments(tmp_path):
    control = _control()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dispatch = bin_dir / "developer-a-ci-dispatch"
    shutil.copyfile(control / "bin/developer-a-ci-dispatch", dispatch)
    dispatch.chmod(0o755)
    capture = tmp_path / "captured-argv"
    target = bin_dir / "production-image-precache-v316-attempt2"
    target.write_text("#!/usr/bin/env bash\nprintf '%s\n' \"$@\" > \"$PRECACHE_CAPTURE\"\n")
    target.chmod(0o755)
    sha = "a" * 40

    def invoke(command):
        return subprocess.run(
            [_bash_exe(), _bash_path(dispatch)], input="stdin-token", text=True, capture_output=True,
            env=dict(os.environ, SSH_ORIGINAL_COMMAND=command,
                     PRECACHE_CAPTURE=_bash_path(capture)),
            timeout=10,
        )

    valid = invoke(f"precache-v316-attempt2 --cache-controller-sha={sha} --registry-user=cache-test")
    assert valid.returncode == 0, valid.stderr
    assert capture.read_text().splitlines() == [
        f"--cache-controller-sha={sha}", "--registry-user=cache-test"]
    for invalid in (
        f"precache-v316-attempt2 --cache-controller-sha={sha} --registry-user=cache-test --unknown=x",
        f"precache-v316-attempt2 --cache-controller-sha={sha} --cache-controller-sha={sha} --registry-user=cache-test",
        f"precache-v316-attempt2 --cache-controller-sha={sha}",
        f"precache-v316-attempt2 --cache-controller-sha={'b' * 40} --registry-user=cache-test;id",
        f"precache-v316-attempt2 --cache-controller-sha={sha} --registry-user=cache-test\ncheck",
        f"precache-v316-attempt2 --cache-controller-sha={sha} --registry-user=cache-test\rcheck",
        f"precache-v316-attempt2 --registry-user=cache-test --cache-controller-sha={sha}",
    ):
        capture.unlink(missing_ok=True)
        result = invoke(invalid)
        assert result.returncode != 0
        assert not capture.exists()

def test_baseline_ci_passes_with_python_entrypoint_and_rejects_bad_interpreters(tmp_path):
    baseline_env = None
    if os.name == "nt":
        shim = tmp_path / "python-shim"
        shim.mkdir()
        (shim / "python3").write_text(
            "#!/usr/bin/env bash\nexec '" + _bash_path(sys.executable) + "' \"$@\"\n")
        (shim / "python3").chmod(0o755)
        baseline_env = dict(os.environ, PATH=_bash_path(shim) + ":/usr/bin:/bin")
    current = _run_ci_baseline(_repo_root(), baseline_env)
    assert current.returncode == 0, current.stdout + current.stderr
    assert "PRODUCTION_BASELINE_CI=PASS" in current.stdout

    fixture = tmp_path / "fixture"
    target = _minimal_repo_fixture(fixture)

    python_entry = target / "bin" / "production-image-precache-v316-attempt2"
    bash_entry = target / "bin" / "developer-a-ci-dispatch"
    original_python = _control() / "bin" / python_entry.name
    original_bash = _control() / "bin" / bash_entry.name

    python_entry.write_text("#!/usr/bin/python3\ndef broken(:\n    pass\n")
    result = _run_ci_baseline(fixture, baseline_env)
    assert result.returncode != 0
    assert "invalid syntax" in result.stderr

    shutil.copyfile(original_python, python_entry)
    bash_entry.write_text("#!/usr/bin/env bash\nif then\n")
    result = _run_ci_baseline(fixture, baseline_env)
    assert result.returncode != 0
    assert "invalid Bash syntax" in result.stderr

    shutil.copyfile(original_bash, bash_entry)
    python_entry.write_text("#!/usr/bin/env ruby\nputs 'not allowed'\n")
    result = _run_ci_baseline(fixture, baseline_env)
    assert result.returncode != 0
    assert "unrecognized interpreter" in result.stderr
