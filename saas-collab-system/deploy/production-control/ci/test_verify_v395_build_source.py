import hashlib
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).with_name("verify_v395_build_source.py")
spec = importlib.util.spec_from_file_location("verify_v395_build_source", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerifyV395BuildSourceTests(unittest.TestCase):
    def setUp(self):
        self.pinned_migration_sha = verifier.MIGRATION_SHA256
        verifier.NOTES_SHA256 = hashlib.sha256(b"notes").hexdigest()
        verifier.MIGRATION_SHA256 = hashlib.sha256(
            b"apps/a/migrations/0001_initial.pymigration-content").hexdigest()
        self.pr = {"number": 535, "state": "open", "merged": False, "draft": True,
                   "auto_merge": None,
                   "merge_commit_sha": "a" * 40,
                   "head": {"sha": verifier.SOURCE, "ref": verifier.HEAD_REF,
                            "repo": {"full_name": verifier.REPO}},
                   "base": {"sha": verifier.PARENT, "ref": verifier.BASE_REF,
                            "repo": {"full_name": verifier.REPO}}}
        self.runs, self.jobs = {}, {}
        self.migration_path = "saas-collab-system/backend/apps/a/migrations/0001_initial.py"
        self.blobs = {self.migration_path: b"migration-content",
                      verifier.NOTES_PATH: b"notes"}
        self.synthetic = {"sha": "a" * 40, "tree": {"sha": verifier.TREE},
                          "parents": [{"sha": verifier.PARENT}, {"sha": verifier.SOURCE}]}
        names = ["Repository safety and file guard", "Django and pytest",
                 "Frontend build observation gate", "Docker Compose configuration",
                 "RPA samples and required documents",
                 "Repository safety and forbidden file guard",
                 "Phase 3 Django, data quality, and pytest",
                 "Frontend build without dependency lifecycle scripts",
                 "Docker Compose placeholder configuration", "RPA samples and Phase 3 documents"]
        for i, (run_id, (_, path)) in enumerate(verifier.PHASES.items()):
            self.runs[run_id] = {"id": run_id, "workflow_id": verifier.PHASES[run_id][0], "path": path,
                "pull_requests": [{"number": verifier.PR_NUMBER, "head": {"sha": verifier.SOURCE},
                                   "base": {"sha": verifier.PARENT}}], "event": "pull_request",
                "head_sha": verifier.SOURCE, "head_branch": verifier.HEAD_REF,
                "run_attempt": 1, "status": "completed", "conclusion": "success"}
            self.jobs[run_id] = [{"id": run_id * 10 + j, "name": name, "run_id": run_id,
                "head_sha": verifier.SOURCE, "run_attempt": 1, "status": "completed",
                "conclusion": "success", "check_run_url": "https://api.github.com/repos/dfcy-team/dfcy/check-runs/" + str(run_id * 10 + j)}
                for j, name in enumerate(names[i * 5:(i + 1) * 5])]
        self.expected_check_ids = {j["id"] for group in self.jobs.values() for j in group}

    def git(self, *args):
        if args == ("rev-parse", verifier.SOURCE + "^{tree}"):
            return verifier.TREE
        if args == ("rev-list", "--parents", "-n", "1", verifier.SOURCE):
            return verifier.SOURCE + " " + verifier.PARENT
        if args == ("diff", "--name-only", verifier.PARENT, verifier.SOURCE):
            return verifier.NOTES_PATH
        if args == ("ls-tree", "-r", "--name-only", verifier.SOURCE):
            return self.migration_path
        raise AssertionError(args)

    def blob(self, path):
        return self.blobs[path]

    def api(self, path):
        if path == "pulls/535": return self.pr
        if path == "git/commits/" + self.pr["merge_commit_sha"]: return self.synthetic
        if path.startswith("actions/runs/") and "/attempts/" not in path:
            return self.runs[int(path.rsplit("/", 1)[1])]
        if "/jobs?" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            return {"total_count": 5, "jobs": self.jobs[rid]}
        if path == "commits/" + verifier.SOURCE + "/check-runs?per_page=100&page=1":
            checks = [{"id": j["id"], "name": j["name"], "head_sha": verifier.SOURCE,
                       "status": "completed", "conclusion": "success", "app": {"id": 15368}}
                      for group in self.jobs.values() for j in group if j["id"] in self.expected_check_ids]
            return {"total_count": 10, "check_runs": checks}
        raise AssertionError(path)

    def verify(self):
        return verifier.verify(verifier.SOURCE, git=self.git, api=self.api, blob=self.blob)

    def test_exact_source_and_successful_ten_checks_pass(self):
        self.assertEqual(self.verify(), hashlib.sha256(
            b"apps/a/migrations/0001_initial.pymigration-content").hexdigest())

    def test_wrong_requested_sha_tree_or_parent_fails(self):
        with self.assertRaises(ValueError): verifier.verify("f" * 40, git=self.git, api=self.api)
        for args, result in [(("rev-parse", verifier.SOURCE + "^{tree}"), "f" * 40),
                             (("rev-list", "--parents", "-n", "1", verifier.SOURCE), verifier.SOURCE + " " + "f" * 40)]:
            original = self.git
            self.git = lambda *a, _args=args, _result=result: _result if a == _args else original(*a)
            with self.assertRaises(ValueError): self.verify()
            self.git = original

    def test_pr_identity_notes_and_subdiff_fail_closed(self):
        self.pr["draft"] = False
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.pr["base"]["sha"] = "f" * 40
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        with self.assertRaisesRegex(ValueError, "notes fingerprint"):
            verifier.verify(verifier.SOURCE, git=self.git, api=self.api, blob=lambda _: b"tampered")
        self.setUp()
        self.git = lambda *a: "extra.py" if a[0] == "diff" else VerifyV395BuildSourceTests.git(self, *a)
        with self.assertRaisesRegex(ValueError, "subdiff"):
            self.verify()

    def test_ci_attempt_failure_or_missing_check_fails(self):
        rid = next(iter(self.runs))
        self.runs[rid]["run_attempt"] = 2
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.jobs[rid][0]["conclusion"] = "failure"
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.api = lambda path: {"total_count": 9, "check_runs": []} if path.startswith("commits/") else VerifyV395BuildSourceTests.api(self, path)
        with self.assertRaisesRegex(ValueError, "check-runs"):
            self.verify()

    def test_synthetic_merge_pr_link_and_job_check_mapping_fail_closed(self):
        self.synthetic["parents"].reverse()
        with self.assertRaisesRegex(ValueError, "synthetic merge"):
            self.verify()
        self.setUp()
        next(iter(self.runs.values()))["pull_requests"] = []
        with self.assertRaisesRegex(ValueError, "workflow run identity"):
            self.verify()
        self.setUp()
        self.jobs[next(iter(self.jobs))][0]["check_run_url"] = "https://example.invalid/1"
        with self.assertRaisesRegex(ValueError, "check-run URL"):
            self.verify()
        self.setUp()
        first = self.jobs[next(iter(self.jobs))][0]
        first["id"] += 100
        first["check_run_url"] = "https://api.github.com/repos/dfcy-team/dfcy/check-runs/" + str(first["id"])
        with self.assertRaisesRegex(ValueError, "source check-runs|map to successful source"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
