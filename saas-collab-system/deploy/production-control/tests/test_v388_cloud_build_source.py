import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "ci" / "verify_v388_cloud_source.py"
spec = importlib.util.spec_from_file_location("verify_v388_cloud_source", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class VerifyV388CloudSourceTests(unittest.TestCase):
    def setUp(self):
        self.pr = {"number": 521, "state": "open", "merged": False, "draft": True,
                   "auto_merge": None,
                   "head": {"sha": verifier.SOURCE, "ref": verifier.HEAD_REF,
                            "repo": {"full_name": verifier.REPO}},
                   "base": {"sha": verifier.PARENT, "ref": verifier.BASE_REF,
                            "repo": {"full_name": verifier.REPO}}}
        self.pr["merge_commit_sha"] = "a" * 40
        self.synthetic = {"sha": "a" * 40, "tree": {"sha": verifier.TREE},
                          "parents": [{"sha": verifier.PARENT}, {"sha": verifier.SOURCE}]}
        self.runs = {}
        self.jobs = {}
        for run_id, (workflow, names) in verifier.PHASES.items():
            self.runs[run_id] = {"id": run_id, "workflow_id": workflow,
                "pull_requests": [{"number": 521, "head": {"sha": verifier.SOURCE}, "base": {"sha": verifier.PARENT}}],
                "event": "pull_request", "head_sha": verifier.SOURCE,
                "head_branch": verifier.HEAD_REF, "run_attempt": 1,
                "path": ".github/workflows/phase2-ci.yml" if run_id == 42308488585 else ".github/workflows/phase3-ci.yml",
                "status": "completed", "conclusion": "success"}
            self.jobs[run_id] = [{"id": run_id * 10 + i, "name": name,
                "run_id": run_id, "head_sha": verifier.SOURCE,
                "status": "completed", "conclusion": "success", "run_attempt": 1,
                "check_run_url": "https://api.github.com/repos/dfcy-team/dfcy/check-runs/" + str(run_id * 10 + i)}
                for i, name in enumerate(names)]

    def git(self, *args):
        if args == ("rev-parse", verifier.SOURCE + "^{tree}"):
            return verifier.TREE
        if args == ("rev-list", "--parents", "-n", "1", verifier.SOURCE):
            return verifier.SOURCE + " " + verifier.PARENT
        if args == ("diff-tree", "--no-commit-id", "--name-only", "-r", verifier.SOURCE):
            return "\n".join(sorted(verifier.FILES))
        raise AssertionError(args)

    def api(self, path):
        if path == "pulls/521":
            return self.pr
        if path == "git/commits/" + self.pr["merge_commit_sha"]:
            return self.synthetic
        if path.startswith("actions/runs/") and "/attempts/" not in path and path.count("/") == 2:
            return self.runs[int(path.rsplit("/", 1)[1])]
        if "/jobs?" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            jobs = self.jobs[rid]
            return {"total_count": len(jobs), "jobs": jobs}
        if path == "commits/" + verifier.SOURCE + "/check-runs?per_page=100&page=1":
            checks = [{"id": j["id"], "name": j["name"], "head_sha": verifier.SOURCE,
                       "status": "completed", "conclusion": "success", "app": {"id": 15368}}
                      for group in self.jobs.values() for j in group]
            return {"total_count": len(checks), "check_runs": checks}
        raise AssertionError(path)

    def verify(self):
        return verifier.verify(verifier.SOURCE, git=self.git, api=self.api)

    def test_valid_source_passes(self):
        self.assertEqual(self.verify(), verifier.SOURCE)

    def test_requested_source_tree_and_parents_are_pinned(self):
        with self.assertRaises(ValueError): verifier.verify("f" * 40, git=self.git, api=self.api)
        original = self.git
        self.git = lambda *a: "f" * 40 if a[0] == "rev-parse" else original(*a)
        with self.assertRaisesRegex(ValueError, "tree mismatch"): self.verify()

    def test_pr_must_remain_same_repo_open_draft_without_merge(self):
        for key, value in (("draft", False), ("merged", True), ("state", "closed")):
            self.pr[key] = value
            with self.assertRaises(ValueError): self.verify()
            self.setUp()
        self.pr["head"]["repo"]["full_name"] = "fork/dfcy"
        with self.assertRaises(ValueError): self.verify()

    def test_wrong_run_and_incomplete_or_wrong_jobs_fail(self):
        rid = next(iter(self.runs))
        self.runs[rid]["run_attempt"] = 2
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.jobs[rid].pop()
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.jobs[rid][0]["conclusion"] = "failure"
        with self.assertRaises(ValueError): self.verify()

    def test_job_check_must_be_source_actions_check(self):
        self.jobs[next(iter(self.jobs))][0]["check_run_url"] = "https://example.invalid/other/999"
        with self.assertRaises(ValueError):
            self.verify()

    def test_changed_pr_or_synthetic_checkout_fails(self):
        self.runs[next(iter(self.runs))]["pull_requests"][0]["number"] += 1
        with self.assertRaises(ValueError): self.verify()
        self.setUp()
        self.synthetic["parents"].reverse()
        with self.assertRaises(ValueError): self.verify()

    def test_job_from_another_run_or_head_fails(self):
        job = self.jobs[next(iter(self.jobs))][0]
        for key, value in (("run_id", 100), ("head_sha", "f"*40)):
            before = job[key]
            job[key] = value
            with self.assertRaises(ValueError): self.verify()
            job[key] = before


if __name__ == "__main__":
    unittest.main()
