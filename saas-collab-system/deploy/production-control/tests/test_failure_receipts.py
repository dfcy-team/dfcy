import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "saas-collab-system/deploy/production-control/ci/write_failure_receipt.ps1"


def test_failure_receipt_is_structured_and_does_not_echo_secrets(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh is required for PowerShell helper test")
    destination = tmp_path / "receipt.json"
    secret = "pseudo-secret-DO-NOT-EMIT"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(HELPER), "-Path", str(destination),
         "-Stage", "cache", "-Reason", "ssh_exit_nonzero", "-ExitCode", "23",
         "-RunId", "1234", "-Attempt", "2", "-ReleaseSha", "f" * 40,
         "-ControllerSha", "a" * 40],
        capture_output=True, text=True, env={**os.environ, "PSEUDO_SECRET": secret},
        check=True,
    )
    receipt = json.loads(destination.read_text(encoding="utf-8"))
    assert receipt == {
        "status": "failure", "stage": "cache", "exit_code": 23, "run_id": "1234",
        "attempt": "2", "release_sha": "f" * 40, "controller_sha": "a" * 40,
        "reason": "ssh_exit_nonzero",
    }
    assert secret not in result.stdout + result.stderr + destination.read_text(encoding="utf-8")


def test_workflow_uploads_failure_diagnostics_and_drains_ssh_streams():
    workflow = (ROOT / ".github/workflows/developer-a-production-release.yml").read_text(encoding="utf-8")
    assert workflow.count("if: failure()") >= 3
    assert workflow.count("production-failure-receipt.json") >= 5
    assert workflow.count("ReadToEndAsync()") >= 6
    assert "[Console]::Out.Write($stdout)" in workflow
    jobs = yaml.safe_load(workflow)["jobs"]
    for job_name in ("remote-deploy", "precache-v316-attempt2", "deploy-v316-manifest-reuse"):
        invocation = "\n".join(step.get("run", "") for step in jobs[job_name]["steps"])
        assert invocation.index("$receiptHelper =") < invocation.index("& $receiptHelper")
        assert invocation.index("$diagnostic =") < invocation.index("& $receiptHelper")


def test_pwsh_nonzero_process_writes_receipt_and_success_does_not(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("pwsh is required for process behavior test")
    secret = "pseudo-secret-DO-NOT-EMIT"

    def invoke(exit_code, receipt_path):
        command = r'''
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $env:TEST_PWSH
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.ArgumentList.Add('-NoProfile')
$psi.ArgumentList.Add('-Command')
$psi.ArgumentList.Add("exit $env:CHILD_EXIT")
$p = [Diagnostics.Process]::Start($psi)
$out = $p.StandardOutput.ReadToEndAsync()
$err = $p.StandardError.ReadToEndAsync()
$p.WaitForExit()
[void]$out.GetAwaiter().GetResult()
[void]$err.GetAwaiter().GetResult()
if ($p.ExitCode -ne 0) {
  & $env:RECEIPT_HELPER -Path $env:RECEIPT_PATH -Stage deploy -Reason ssh_exit_nonzero -ExitCode $p.ExitCode -RunId '321' -Attempt '1' -ReleaseSha ('f' * 40) -ControllerSha ('a' * 40)
}
'''
        return subprocess.run(
            [pwsh, "-NoProfile", "-Command", command], capture_output=True, text=True,
            env={**os.environ, "TEST_PWSH": pwsh, "CHILD_EXIT": str(exit_code),
                 "RECEIPT_HELPER": str(HELPER), "RECEIPT_PATH": str(receipt_path),
                 "PSEUDO_SECRET": secret}, check=True,
        )

    failed_path = tmp_path / "failed.json"
    failure = invoke(17, failed_path)
    receipt = json.loads(failed_path.read_text(encoding="utf-8"))
    assert receipt["exit_code"] == 17 and receipt["reason"] == "ssh_exit_nonzero"
    assert secret not in failure.stdout + failure.stderr + failed_path.read_text(encoding="utf-8")

    success_path = tmp_path / "success.json"
    invoke(0, success_path)
    assert not success_path.exists()
