import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "ci"))
import batch_provenance as bp


def fixture():
    cfg = json.loads(bp.CONFIG.read_text(encoding="utf-8"))
    cfg.update(merge_commit_sha="c" * 40, controller_sha="d" * 40)
    ppaths = [f"business/{i:03}" for i in range(121)]
    hpaths = set(ppaths[:69])
    safe = ["docs/approved.txt"]
    trees = {}
    trees[cfg["source_parent"]] = {p: "100644 blob oldP" + p for p in ppaths}
    trees[cfg["source_sha"]] = {p: "100644 blob newS" + p for p in ppaths}
    trees[cfg["integration_parent"]] = {p: ("100644 blob oldC" + p if p in hpaths else "100644 blob newS" + p) for p in ppaths}
    trees[cfg["integration_parent"]].update({p: "100644 blob safe" for p in safe})
    trees[cfg["integration_sha"]] = dict(trees[cfg["integration_parent"]])
    for p in hpaths:
        trees[cfg["integration_sha"]][p] = trees[cfg["source_sha"]][p]
    trees[cfg["merge_commit_sha"]] = dict(trees[cfg["integration_sha"]])
    commits = {
        cfg["source_sha"]: (cfg["source_parent"], cfg["source_tree"]),
        cfg["integration_sha"]: (cfg["integration_parent"], cfg["integration_tree"]),
        cfg["merge_commit_sha"]: (cfg["integration_parent"], cfg["integration_tree"]),
    }
    def fake_git(root, *args):
        if args == ("rev-parse", "HEAD") or args == ("rev-parse", "origin/main"):
            return cfg["controller_sha"]
        if args == ("merge-base", "--is-ancestor", cfg["merge_commit_sha"], cfg["controller_sha"]):
            return ""
        if args[:3] == ("show", "-s", "--format=%P"):
            return commits[args[3]][0]
        if args[:3] == ("show", "-s", "--format=%T"):
            return commits[args[3]][1]
        if args[0] == "diff-tree":
            before, after = args[-2:]
            if (before, after) == (cfg["source_parent"], cfg["source_sha"]):
                return "\n".join(ppaths)
            if (before, after) == (cfg["integration_parent"], cfg["integration_sha"]):
                return "\n".join(sorted(hpaths))
        if args[0] == "ls-tree":
            tree = trees[args[-1]]
            return "\n".join(f"{meta}\t{path}" for path, meta in sorted(tree.items()))
        raise AssertionError(args)
    checks = [{"name": n, "head_sha": sha, "status": "completed", "conclusion": "success",
               "app": {"id": 15368, "slug": "github-actions"}}
              for sha in (cfg["source_sha"], cfg["integration_sha"], cfg["merge_commit_sha"])
              for n in bp.CONTEXTS]
    pr = {"number": cfg["pull_request_number"], "base": {"ref": "main", "repo": {"full_name": bp.REPO}},
          "head": {"sha": cfg["integration_sha"], "repo": {"full_name": bp.REPO}},
          "merged": True, "merge_commit_sha": cfg["merge_commit_sha"]}
    return cfg, fake_git, pr, checks


class ProvenanceTests(unittest.TestCase):
    def test_unmerged_or_unapproved_identities_fail_closed(self):
        cfg, *_ = fixture()
        cfg["merge_commit_sha"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity is unbound"):
                bp.identity(path)

    def test_source_and_baseline_migration_digests_are_distinct(self):
        cfg = json.loads(bp.CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["source_migration_sha256"], "696734a0a1ade1064cc9519018e51223c658d8db13f71154e97498fadb55a740")
        self.assertEqual(cfg["baseline_migration_sha256"], "7628bb3e116b30baa7e61d2b1df75367d77fe452773778b4dde3f6476586deb3")
        self.assertEqual(cfg["source_path_count"], 121)

    def test_ci_only_policy_passes_without_review_records(self):
        cfg, fake_git, pr, checks = fixture()
        with patch.object(bp, "git", side_effect=fake_git):
            bp.validate(Path.cwd(), cfg["controller_sha"], bp.REPO, pr, checks, cfg)

    def test_rejects_wrong_identity_policy_and_incomplete_or_failed_ci(self):
        cases = ("parent", "tree", "path", "unmerged", "checks", "failed_ci", "wrong_app", "wrong_sha", "policy")
        for case in cases:
            cfg, fake_git, pr, checks = fixture()
            if case == "parent":
                original = fake_git
                def fake_git(root, *args):
                    if args[:3] == ("show", "-s", "--format=%P") and args[3] == cfg["integration_sha"]:
                        return cfg["source_sha"] + " " + cfg["integration_parent"]
                    return original(root, *args)
            elif case == "tree":
                cfg["integration_tree"] = "e" * 40
            elif case == "path":
                original = fake_git
                def fake_git(root, *args):
                    if args[0] == "diff-tree" and args[-2:] == (cfg["integration_parent"], cfg["integration_sha"]):
                        return original(root, *args) + "\nrogue/path"
                    return original(root, *args)
            elif case == "unmerged":
                pr["merged"] = False
            elif case == "checks":
                checks.pop()
            elif case == "failed_ci":
                checks[0]["conclusion"] = "failure"
            elif case == "wrong_app":
                checks[0]["app"]["id"] = 0
            elif case == "wrong_sha":
                checks[0]["head_sha"] = "f" * 40
            elif case == "policy":
                cfg["review_policy"] = "unknown"
            with self.subTest(case=case), patch.object(bp, "git", side_effect=fake_git), self.assertRaises(ValueError):
                bp.validate(Path.cwd(), cfg["controller_sha"], bp.REPO, pr, checks, cfg)

    def test_old_action_is_absent_but_v330_route_is_selectable(self):
        workflow = Path(__file__).parents[4] / ".github/workflows/developer-a-production-release.yml"
        dispatch = Path(__file__).parents[1] / "bin/developer-a-ci-dispatch"
        w, d = workflow.read_text(encoding="utf-8"), dispatch.read_text(encoding="utf-8")
        allow = w.split('case "$action" in', 1)[1].split(';;', 1)[0]
        choices = w.split("options:", 1)[1].split("transport:", 1)[0]
        self.assertIn("preflight-v330", allow)
        self.assertIn("deploy-v330-manifest-reuse", choices)
        self.assertNotIn("batch317-320", allow + choices + d)
        self.assertIn("preflight-v330)", d)


if __name__ == "__main__":
    unittest.main()
