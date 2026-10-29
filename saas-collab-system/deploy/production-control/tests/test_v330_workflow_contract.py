"""Execute the real workflow evidence step with synthetic GitHub API responses."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/developer-a-production-release.yml").read_text(encoding="utf-8"))
BUILD = yaml.safe_load((ROOT / ".github/workflows/production-artifacts-build-only.yml").read_text(encoding="utf-8"))

class WorkflowContractTests(unittest.TestCase):
    def test_fetch_recovers_deleted_integration_branch_and_rejects_wrong_head(self):
        step = next(s for s in WORKFLOW['jobs']['validate']['steps'] if s.get('name') == 'Fetch exact V330 provenance commits')
        self.assertIn("inputs.action == 'preflight-v330'", step['if'])
        self.assertIn("inputs.action == 'deploy-v330-manifest-reuse'", step['if'])
        bash = str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git/bin/bash.exe') if os.name == 'nt' else shutil.which('bash')
        self.assertTrue(bash)
        env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        def git(root, *args, input=None, check=True):
            return subprocess.run(['git', '-C', str(root), *args], input=input, env=env, capture_output=True, text=True, check=check)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); origin=root/'origin.git'; client=root/'client'
            origin.mkdir(); client.mkdir()
            git(origin,'init','--bare'); tree=git(origin,'mktree',input='').stdout.strip()
            parent=git(origin,'commit-tree',tree,'-m','base').stdout.strip()
            integration=git(origin,'commit-tree',tree,'-p',parent,'-m','integration').stdout.strip()
            main=git(origin,'commit-tree',tree,'-p',parent,'-m','squash merge').stdout.strip()
            source=git(origin,'commit-tree',tree,'-p',parent,'-m','source').stdout.strip()
            for ref,sha in [('refs/heads/main',main),('refs/heads/source',source),('refs/pull/418/head',integration)]: git(origin,'update-ref',ref,sha)
            git(client,'init'); git(client,'remote','add','origin',origin.as_uri())
            git(client,'fetch','--no-tags','origin','+refs/heads/*:refs/remotes/origin/*')
            git(client,'checkout','--detach','origin/main')
            self.assertNotEqual(git(client,'cat-file','-e',integration,check=False).returncode,0)
            config=client/'saas-collab-system/deploy/production-control/ci/v330-release-identity.json';config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'source_sha':source,'integration_sha':integration,'pull_request_number':418}),encoding='utf-8')
            result=subprocess.run([bash,'-c',step['run']],cwd=client,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(git(client,'rev-parse','FETCH_HEAD').stdout.strip(),integration)
            git(origin,'update-ref','refs/pull/418/head',main)
            result=subprocess.run([bash,'-c',step['run']],cwd=client,env=env,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0)

    def test_bind_step_receives_independent_approval(self):
        step = next(s for s in WORKFLOW["jobs"]["deploy-v330-manifest-reuse"]["steps"] if s.get("id") == "bind")
        self.assertEqual(step["env"]["V330_APPROVED_BUILD_CONTROLLER_SHA"], "${{ vars.V330_APPROVED_BUILD_CONTROLLER_SHA }}")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required for executable workflow test")
    def test_real_preflight_source_step_accepts_actual_job_names_and_rejects_unapproved(self):
        step = next(s for s in WORKFLOW["jobs"]["preflight-v330"]["steps"] if s.get("id") == "source")
        sha = "a" * 40
        controller = "b" * 40
        names = [job.get("name", key) for key, job in BUILD["jobs"].items()]
        run = {"head_sha": controller, "path": ".github/workflows/production-artifacts-build-only.yml", "event": "workflow_dispatch", "head_branch": "main", "run_attempt": 1, "status": "completed", "conclusion": "success"}
        jobs = {"total_count": len(names), "jobs": [{"name": name, "status": "completed", "conclusion": "success"} for name in names]}
        artifacts = {"total_count": 1, "artifacts": [{"name": f"production-build-only-{sha}-12345-1", "expired": False}]}
        prefix = "function Invoke-RestMethod { param($Uri, $Headers)\n"
        prefix += "if ($Uri -like '*jobs?*') { return '" + json.dumps(jobs) + "' | ConvertFrom-Json }\n"
        prefix += "if ($Uri -like '*artifacts?*') { return '" + json.dumps(artifacts) + "' | ConvertFrom-Json }\n"
        prefix += "return '" + json.dumps(run) + "' | ConvertFrom-Json\n}\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "saas-collab-system/deploy/production-control/ci/v330-release-identity.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"source_sha": sha}), encoding="utf-8")
            script = root / "source.ps1"
            script.write_text(prefix + step["run"], encoding="utf-8")
            env = dict(os.environ, GITHUB_WORKSPACE=str(root), GITHUB_REPOSITORY="dfcy-team/dfcy", BUILD_RUN_ID="12345", GITHUB_OUTPUT=str(root / "output"), GH_API_TOKEN="workflow-test-placeholder-token", V330_APPROVED_BUILD_CONTROLLER_SHA=controller)
            command = [shutil.which("pwsh"), "-NoProfile", "-File", str(script)]
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("build_controller_sha=" + controller, (root / "output").read_text())
            env["V330_APPROVED_BUILD_CONTROLLER_SHA"] = "c" * 40
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main()
