import copy
import hashlib
import json
import subprocess
import unittest

import verify_v384_cloud_source as verifier


IDENTITY = json.loads(verifier.IDENTITY.read_text(encoding="utf-8"))
SOURCE = IDENTITY["source_sha"]


class VerifyV384CloudSourceTests(unittest.TestCase):
    def setUp(self):
        self.identity = copy.deepcopy(IDENTITY)
        self.pr = {"number": 501, "state": "open",
                   "head": {"sha": SOURCE, "repo": {"full_name": verifier.REPO}},
                   "base": {"ref": "main", "sha": self.identity["pull_request_base_sha"],
                            "repo": {"full_name": verifier.REPO}}}
        self.checks = [{"id": n, "name": name, "status": "completed", "conclusion": "success",
                        "head_sha": SOURCE} for n, name in enumerate(self.identity["checks"], 1)]

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True).strip()

    def api(self, path):
        if path == "pulls/501":
            return self.pr
        if path == "commits/" + SOURCE + "/check-runs?per_page=100&page=1":
            return {"total_count": len(self.checks), "check_runs": self.checks}
        raise AssertionError(path)

    def run_verify(self, requested=SOURCE):
        return verifier.verify(requested, identity=self.identity, git=self.git, api=self.api)

    def test_exact_source_passes(self):
        self.assertEqual(self.run_verify(), IDENTITY["migration_sha256"])

    def test_actual_source_tree_and_migration_fingerprint(self):
        tree = self.git("rev-parse", "--verify", SOURCE + "^{tree}")
        self.assertEqual(tree, "60c02cfe56682a661a502ea0f48a86ac06e5be75")
        listing = subprocess.check_output(["git", "ls-tree", "--full-tree", "-r", SOURCE], text=True)
        digest = hashlib.sha256()
        migrations = []
        for line in listing.splitlines():
            metadata, name = line.split("\t", 1)
            if "/migrations/" in name and name.endswith(".py"):
                oid = metadata.split()[2]
                migrations.append((name, oid))
        for name, oid in sorted(migrations):
            digest.update(name.removeprefix("saas-collab-system/backend/").encode())
            digest.update(subprocess.check_output(["git", "cat-file", "blob", oid]))
        self.assertEqual(digest.hexdigest(), IDENTITY["migration_sha256"])

    def test_other_source_and_false_sha_fail(self):
        for sha in ("f" * 40, "not-a-sha"):
            with self.assertRaises(ValueError):
                self.run_verify(sha)

    def test_tree_and_parent_mismatch_fail_closed(self):
        self.identity["source_tree"] = "f" * 40
        with self.assertRaises(ValueError): self.run_verify()
        self.identity = copy.deepcopy(IDENTITY)
        self.identity["parent_sha"] = "f" * 40
        with self.assertRaises(ValueError): self.run_verify()

    def test_file_hash_pr_base_and_missing_check_fail_closed(self):
        self.identity["files"][next(iter(self.identity["files"]))] = "f" * 64
        with self.assertRaises(ValueError): self.run_verify()
        self.identity = copy.deepcopy(IDENTITY)
        self.pr["base"]["sha"] = "f" * 40
        with self.assertRaises(ValueError): self.run_verify()
        self.pr["base"]["sha"] = IDENTITY["pull_request_base_sha"]
        self.checks.pop()
        with self.assertRaises(ValueError): self.run_verify()

    def test_latest_failure_overrides_older_success(self):
        self.checks.append({"id": 11, "name": self.identity["checks"][0], "status": "completed",
                            "conclusion": "failure", "head_sha": SOURCE})
        with self.assertRaises(ValueError): self.run_verify()

    def test_incomplete_and_duplicate_pages_fail_closed(self):
        self.checks = [{"id": n, "name": "irrelevant", "status": "completed",
                        "conclusion": "success", "head_sha": SOURCE} for n in range(100)]
        def incomplete(path):
            if path == "pulls/501": return self.pr
            if path.endswith("page=1"):
                return {"total_count": 101, "check_runs": self.checks}
            return {"total_count": 101, "check_runs": []}
        with self.assertRaises(ValueError):
            verifier.verify(SOURCE, identity=self.identity, git=self.git, api=incomplete)
        def duplicate(path):
            if path == "pulls/501": return self.pr
            if path.endswith("page=1"):
                return {"total_count": 101, "check_runs": self.checks}
            return {"total_count": 101, "check_runs": [self.checks[0]]}
        with self.assertRaises(ValueError):
            verifier.verify(SOURCE, identity=self.identity, git=self.git, api=duplicate)

if __name__ == "__main__":
    unittest.main()
