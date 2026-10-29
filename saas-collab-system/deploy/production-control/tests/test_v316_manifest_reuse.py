import os
import shutil
import subprocess
import base64
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_PATH = ROOT / ".github/workflows/developer-a-production-release.yml"
SOURCE_SHA = "f9827a0a89b622997f1c2633411ec9ef2758839a"
SOURCE_CONTROLLER_SHA = "fb20a0adb932e07c7d206d05807b80c80076696f"
CACHE_CONTROLLER_SHA = "31fabe1837c3fb3f7eff5c292dca8def0a7c4b19"
MANIFEST_SHA = "3d437f40b274a4e12846691c31337bc69f052f31d344cfb9aba7869cd952097d"


def _workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _reuse_job():
    return _workflow()["jobs"]["deploy-v316-manifest-reuse"]


def _step(name):
    return next(step for step in _reuse_job()["steps"] if step.get("name") == name)


def _pwsh():
    executable = shutil.which("pwsh")
    assert executable, "PowerShell Core is required for workflow guard tests"
    return executable


def _run_pwsh(script, env=None):
    return subprocess.run(
        [_pwsh(), "-NoLogo", "-NoProfile", "-EncodedCommand", base64.b64encode(script.encode("utf-16le")).decode("ascii")],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        env=env,
    )


def test_reuse_is_separate_fixed_artifact_deploy_and_never_builds():
    workflow = _workflow()
    jobs = workflow["jobs"]
    job = jobs["deploy-v316-manifest-reuse"]
    assert job["needs"] == "validate"
    assert "needs.build" not in str(job)
    assert "docker/build-push-action" not in str(job)
    artifact = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert artifact["with"]["run-id"] == 40515060731
    assert SOURCE_SHA in str(job)
    assert MANIFEST_SHA in str(job)
    assert job["permissions"]["actions"] == "read"
    assert job["environment"] == "Production"
    assert "inputs.action == 'deploy-v316-manifest-reuse' && github.sha" in str(
        jobs["validate"]["steps"][0]["with"]["ref"]
    )
    assert "release_sha='f9827a0a89b622997f1c2633411ec9ef2758839a'" in str(
        next(step for step in jobs["validate"]["steps"]
             if step.get("name") == "Validate request and main ancestry")["run"]
    )


def test_source_run_gate_accepts_only_exact_run_and_required_job_conclusions(tmp_path):
    gate = _step("Verify fixed source run and its successful gates")["run"]
    gate = gate.replace("${{ needs.validate.outputs.precache_run_id }}", "123456789")
    mock = r'''
function Invoke-RestMethod {
  param($Method, $Uri, $Headers)
  if ($Uri -like '*40515060731/jobs*') {
    return @{ total_count=5; jobs = @(
      @{ name='Validate requested release'; status='completed'; conclusion=$env:MOCK_VALIDATE; completed_at='2026-10-25T00:40:00Z' }
      @{ name='Application quality gates'; status='completed'; conclusion='success'; completed_at='2026-10-25T00:50:00Z' }
      @{ name='Build immutable CI images'; status='completed'; conclusion='success'; completed_at='2026-10-25T00:55:00Z' }
      @{ name='Deploy CI digests to production'; status='completed'; conclusion='failure'; completed_at=$env:MOCK_SOURCE_DEPLOY_COMPLETED }
      @{ name='Skipped control job'; status='completed'; conclusion='skipped'; completed_at=$null }
    ) }
  }
  if ($Uri -like '*123456789/jobs*') {
    return @{ total_count=3; jobs = @(
      @{ name='Validate requested release'; status='completed'; conclusion='success'; completed_at='2026-10-27T02:30:00Z' }
      @{ name='Cache exact V316 attempt-2 images (no deployment)'; status=$env:MOCK_CACHE_JOB_STATUS; conclusion='success'; completed_at=$env:MOCK_CACHE_JOB_COMPLETED }
      @{ name='Skipped deploy job'; status='completed'; conclusion='skipped'; completed_at=$null }
    ) }
  }
  if ($Uri -like '*actions/runs/40515060731') {
    return @{ path='.github/workflows/developer-a-production-release.yml'; event='workflow_dispatch'; head_branch='main'; head_sha=$env:MOCK_SOURCE_SHA; run_attempt=[int]$env:MOCK_SOURCE_ATTEMPT; status='completed'; conclusion='failure' }
  }
  if ($Uri -like '*actions/runs/123456789') {
    return @{ path='.github/workflows/developer-a-production-release.yml'; event='workflow_dispatch'; head_branch='main'; head_sha=$env:MOCK_CACHE_SHA; run_attempt=[int]$env:MOCK_CACHE_ATTEMPT; status='completed'; conclusion='success'; created_at=$env:MOCK_CACHE_CREATED }
  }
  if ($Uri -like '*actions/runs/999999999') {
    return @{ path='.github/workflows/developer-a-production-release.yml'; event='workflow_dispatch'; head_branch='main'; head_sha=$env:GITHUB_SHA; run_attempt=1; status='in_progress'; created_at='2026-10-27T04:00:00Z' }
  }
  throw 'unexpected mock URI'
}
'''
    common = dict(
        os.environ,
        GITHUB_REPOSITORY="dfcy-team/dfcy",
        GH_API_TOKEN="ci-placeholder-token",
        GITHUB_OUTPUT=str(tmp_path / "output"),
        GITHUB_RUN_ID="999999999",
        GITHUB_SHA=CACHE_CONTROLLER_SHA,
        MOCK_SOURCE_SHA=SOURCE_CONTROLLER_SHA,
        MOCK_SOURCE_ATTEMPT="1",
        MOCK_CACHE_SHA=CACHE_CONTROLLER_SHA,
        MOCK_CACHE_ATTEMPT="1",
        MOCK_CACHE_CREATED="2026-10-27T02:00:00Z",
        MOCK_CACHE_JOB_COMPLETED="2026-10-27T03:00:00Z",
        MOCK_CACHE_JOB_STATUS="completed",
        MOCK_SOURCE_DEPLOY_COMPLETED="2026-10-25T01:00:00Z",
    )
    valid = _run_pwsh(mock + "\n" + gate, dict(common, MOCK_VALIDATE="success"))
    assert valid.returncode == 0, valid.stderr

    for env in (
        dict(common, MOCK_SOURCE_SHA=SOURCE_SHA, MOCK_VALIDATE="success"),
        dict(common, MOCK_VALIDATE="failure"),
        dict(common, MOCK_VALIDATE="success", GITHUB_REPOSITORY="other/repo"),
        dict(common, MOCK_VALIDATE="success", MOCK_SOURCE_ATTEMPT="2"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_SHA=SOURCE_CONTROLLER_SHA),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_ATTEMPT="2"),
        dict(common, MOCK_VALIDATE="success", MOCK_SOURCE_DEPLOY_COMPLETED=""),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_JOB_COMPLETED=""),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_JOB_STATUS="in_progress"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_CREATED="2026-10-25T01:00:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_CREATED="2026-10-27T02:30:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_JOB_COMPLETED="2026-10-27T02:30:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_CREATED="2026-10-27T02:00:00Z", MOCK_CACHE_JOB_COMPLETED="2026-10-27T02:00:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_CREATED="2026-10-24T00:30:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_CREATED="2026-10-26T02:00:00Z", MOCK_CACHE_JOB_COMPLETED="2026-10-26T03:00:00Z"),
        dict(common, MOCK_VALIDATE="success", MOCK_CACHE_JOB_COMPLETED="2026-10-27T05:00:00Z"),
    ):
        rejected = _run_pwsh(mock + "\n" + gate, env)
        assert rejected.returncode != 0
        assert "mock" not in (rejected.stdout or "") + (rejected.stderr or "")


def test_manifest_gate_fails_closed_for_changed_bytes_and_invalid_json(tmp_path):
    gate = _step("Verify exact manifest identity")["run"]
    output = tmp_path / "github-output"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = dict(os.environ, GITHUB_OUTPUT=str(output), GITHUB_WORKSPACE=str(workspace))

    (workspace / "release-manifest.json").write_text("{}\n", encoding="utf-8")
    changed = _run_pwsh(gate, env)
    assert changed.returncode != 0
    assert "manifest bytes differ" in (changed.stdout or "") + (changed.stderr or "")

    (workspace / "release-manifest.json").write_text("not-json\n", encoding="utf-8")
    invalid = _run_pwsh(gate, env)
    assert invalid.returncode != 0
    assert "manifest bytes differ" in invalid.stderr


def test_deploy_uses_fixed_forced_command_and_keeps_registry_token_off_argv():
    step = _step("Invoke the fixed forced-command entrypoint with GHCR token on stdin")
    script = step["run"]
    assert "deploy --release-sha=$env:RELEASE_SHA" in script
    assert "--manifest-sha256=$env:MANIFEST_SHA" in script
    assert "--registry-token-stdin" in script
    assert "$reuseProcess.StandardInput.BaseStream.Write($tokenBytes, 0, $tokenBytes.Length)" in script
    assert "$env:GHCR_TOKEN" not in script[script.index("$remote = "):script.index("try {")]
    assert "ssh.exe" in script and "StrictHostKeyChecking=yes" in script
    assert "VM_SSH_PRIVATE_KEY" not in step.get("env", {})


def test_precache_job_captures_only_sanitized_receipt_for_later_predecessor_gate():
    job = _workflow()["jobs"]["precache-v316-attempt2"]
    invocation = next(step["run"] for step in job["steps"] if step.get("name") == "Invoke fixed cache-only command with GHCR token on stdin")
    upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert "$env:GHCR_TOKEN | & ssh.exe" not in invocation
    assert "$cacheProcess.StandardInput.BaseStream.Write($tokenBytes, 0, $tokenBytes.Length)" in invocation
    assert "cache_only_complete" in invocation
    assert "release_controller_sha" in invocation
    assert "cache_workflow_run_id" in invocation and "cache_run_attempt" in invocation
    assert "$env:GITHUB_RUN_ID" in invocation and "$env:GITHUB_RUN_ATTEMPT" in invocation
    assert "cache_workflow_run_id = [long]$env:GITHUB_RUN_ID" in invocation
    assert "cache_run_attempt = [int]$env:GITHUB_RUN_ATTEMPT" in invocation
    assert "manifest_sha256" in invocation
    assert "v316-precache-receipt.json" in invocation
    assert upload["with"]["name"] == "production-v316-precache-receipt"
    proof_gate = _step("Verify cache proof is from the required predecessor run")["run"]
    assert "CACHE_RUN_SHA" in str(_step("Verify cache proof is from the required predecessor run"))
    assert "cache_controller_sha -ne $env:CACHE_RUN_SHA" in proof_gate
    assert "workflow_run_id -ne 40515060731" in proof_gate
    assert "cache_workflow_run_id.ToString() -ne $env:CACHE_RUN_ID" in proof_gate
    assert "cache_run_attempt.ToString() -ne $env:CACHE_RUN_ATTEMPT" in proof_gate
    workflow = _workflow()
    dispatch = workflow.get("on", workflow.get(True))
    assert "precache_run_id" in str(dispatch["workflow_dispatch"]["inputs"])


def test_pre_cache_and_deploy_clean_key_when_known_hosts_write_fails(tmp_path):
    jobs = _workflow()["jobs"]
    cases = (
        (jobs["precache-v316-attempt2"], "Invoke fixed cache-only command with GHCR token on stdin"),
        (jobs["deploy-v316-manifest-reuse"], "Invoke the fixed forced-command entrypoint with GHCR token on stdin"),
    )
    for index, (job, step_name) in enumerate(cases):
        runner_temp = tmp_path / str(index)
        runner_temp.mkdir()
        (runner_temp / "production-known-hosts").mkdir()
        step = next(item for item in job["steps"] if item.get("name") == step_name)
        env = dict(
            os.environ,
            RUNNER_TEMP=str(runner_temp),
            VM_HOST="vm.example.test",
            VM_PORT="22",
            VM_DEPLOY_USER="deploy",
            VM_SSH_PRIVATE_KEY="private-key-test-marker",
            VM_KNOWN_HOSTS="known-hosts-test-marker",
            GHCR_TOKEN="registry-token-test-marker",
            GITHUB_ACTOR="actor-test",
            GITHUB_RUN_ID="123456789",
            GITHUB_RUN_ATTEMPT="1",
            GITHUB_SHA=CACHE_CONTROLLER_SHA,
            REGISTRY_USER="actor-test",
            RELEASE_SHA=SOURCE_SHA,
            MIGRATION_SHA="a" * 64,
            MANIFEST_SHA=MANIFEST_SHA,
            BACKEND_IMAGE="ghcr.io/dfcy-team/dfcy/backend@sha256:" + "a" * 64,
            FRONTEND_IMAGE="ghcr.io/dfcy-team/dfcy/frontend@sha256:" + "b" * 64,
            REDIS_IMAGE="redis@sha256:" + "c" * 64,
        )
        result = _run_pwsh(step["run"], env)
        assert result.returncode != 0
        assert not (runner_temp / "production-ci-key").exists()
        assert "private-key-test-marker" not in (result.stdout or "") + (result.stderr or "")


def test_cache_receipt_gate_rejects_wrong_predecessor_release_manifest_or_images(tmp_path):
    step = _step("Verify cache proof is from the required predecessor run")
    gate = step["run"]
    receipt = {
        "status": "cache_only_complete",
        "workflow_run_id": 40515060731,
        "attempt": 2,
        "cache_workflow_run_id": 123456789,
        "cache_run_attempt": 1,
        "release_sha": SOURCE_SHA,
        "release_controller_sha": "fb20a0adb932e07c7d206d05807b80c80076696f",
        "cache_controller_sha": CACHE_CONTROLLER_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "pull_count": 2,
        "images": [
            "ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:6a943d02b598a7033a24f9c94ef8ed9d5580acaccc13143b6650e74de2669236",
            "ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:de99b6e2e1dcebf6079ad20b3af25a24004feaae4a43279c3f538f08cd9aefa8",
        ],
        "log_sha256": ["b" * 64, "c" * 64],
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    proof_path = workspace / "v316-precache-receipt.json"
    env = dict(os.environ, GITHUB_WORKSPACE=str(workspace), CACHE_RUN_ID="123456789", CACHE_RUN_SHA=CACHE_CONTROLLER_SHA, CACHE_RUN_ATTEMPT="1")

    proof_path.write_text(json.dumps(receipt), encoding="utf-8")
    valid = _run_pwsh(gate, env)
    assert valid.returncode == 0, valid.stderr

    for field, value in (
        ("workflow_run_id", 987654321),
        ("cache_workflow_run_id", 987654321),
        ("cache_run_attempt", 2),
        ("release_sha", "d" * 40),
        ("manifest_sha256", "e" * 64),
        ("cache_controller_sha", SOURCE_CONTROLLER_SHA),
        ("images", ["mutable:latest", "mutable:latest"]),
    ):
        altered = dict(receipt, **{field: value})
        proof_path.write_text(json.dumps(altered), encoding="utf-8")
        rejected = _run_pwsh(gate, env)
        assert rejected.returncode != 0, field


def test_embedded_powershell_parses(tmp_path):
    jobs = _workflow()["jobs"]
    relevant = (jobs["precache-v316-attempt2"], jobs["deploy-v316-manifest-reuse"])
    scripts = [step["run"] for job in relevant for step in job["steps"] if step.get("shell") == "pwsh" or step.get("shell") == "powershell"]
    assert scripts
    for index, script in enumerate(scripts):
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        parser_script = (
            f"$source=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{encoded}'))\n"
            "$tokens=$null; $errors=$null; "
            "[void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors); "
            "if($errors.Count){$errors | ForEach-Object {Write-Error $_.Message}; exit 1}"
        )
        parser_path = tmp_path / f"parse-{index}.ps1"
        parser_path.write_text(parser_script, encoding="utf-8")
        result = subprocess.run(
            [_pwsh(), "-NoLogo", "-NoProfile", "-File", str(parser_path)],
            text=True,
            capture_output=True,
            timeout=20,
            env=dict(os.environ),
        )
        assert result.returncode == 0, result.stderr
