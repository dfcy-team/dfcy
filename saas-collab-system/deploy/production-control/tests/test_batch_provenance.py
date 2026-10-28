import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "ci"))
import batch_provenance as bp


def evidence():
    contexts = sorted(bp.CONTEXTS)
    checks = [{"name": name, "head_sha": sha, "status": "completed", "conclusion": "success",
               "app": {"id": 15368, "slug": "github-actions"}}
              for sha in (bp.S, bp.H, bp.M) for name in contexts]
    pr = {"number": bp.PR, "base": {"ref": "main", "repo": {"full_name": bp.REPO}},
          "head": {"sha": bp.H, "repo": {"full_name": bp.REPO}},
          "merged": True, "merge_commit_sha": bp.M}
    reviews = [{"user": {"login": bp.OWNER}, "state": "APPROVED", "commit_id": bp.H}]
    return pr, reviews, checks


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.expected = {
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "origin/main"): "a" * 40,
            ("merge-base", "--is-ancestor", bp.M, "a" * 40): "",
            ("show", "-s", "--format=%P", bp.S): bp.P,
            ("show", "-s", "--format=%P", bp.H): f"{bp.S} {bp.C}",
            ("show", "-s", "--format=%T", bp.S): bp.S_TREE,
            ("show", "-s", "--format=%T", bp.H): bp.H_TREE,
            ("show", "-s", "--format=%P", bp.M): bp.C,
            ("show", "-s", "--format=%T", bp.M): bp.H_TREE,
            ("diff-tree", "--no-commit-id", "--name-only", "-r", bp.P, bp.S): "\n".join(f"f{i}" for i in range(27)),
            ("diff-tree", "--no-commit-id", "--name-only", "-r", bp.C, bp.H): "\n".join(f"f{i}" for i in range(27)),
        }
        self.real_git = bp.git

        def fake_git(root, *args):
            if args[0] == "ls-tree":
                before = args[-1] in (bp.P, bp.C)
                return "\n".join(f"100644 blob {'before' if before else 'after'}{i}\tf{i}" for i in range(27))
            if args[0] == "rev-parse" and len(args) == 2 and args[1].count(":") == 1:
                return args[1].split(":")[1] + "blob"
            return self.expected[args]
        self.git_patch = patch.object(bp, "git", side_effect=fake_git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)

    def validate(self, mutate=None):
        pr, reviews, checks = evidence()
        if mutate:
            mutate(pr, reviews, checks)
        bp.validate(Path.cwd(), "a" * 40, bp.REPO, pr, reviews, checks)

    def test_fixed_evidence_passes(self):
        self.validate()

    def test_rejects_untrusted_checks_dismissal_and_truncated_reviews(self):
        mutations = [
            lambda p, r, c: c[0].update(app={"id": 123, "slug": "untrusted"}),
            lambda p, r, c: c[0].pop("app"),
            lambda p, r, c: r.append({"user": {"login": bp.OWNER}, "state": "DISMISSED", "commit_id": bp.H}),
            lambda p, r, c: r.extend([{"state": "COMMENTED"}] * 99),
            lambda p, r, c: r.extend([{"state": "COMMENTED"}] * 99 + [{"user": {"login": bp.OWNER}, "state": "CHANGES_REQUESTED"}]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(mutation)

    def test_real_fixed_git_graph(self):
        root = Path(__file__).resolve().parents[4]
        pr, reviews, checks = evidence()
        # Only main identity is represented by this not-yet-merged controller;
        # all fixed S/H/M objects, paths and entries use real Git operations.
        def real_git(root, *args):
            if args == ("rev-parse", "origin/main"):
                return self.real_git(root, "rev-parse", "HEAD")
            return self.real_git(root, *args)
        with patch.object(bp, "git", side_effect=real_git):
            bp.validate(root, self.real_git(root, "rev-parse", "HEAD"), bp.REPO,
                        pr, reviews, checks)

    def test_rejects_wrong_release_pr_merge_tree_approval_and_ci(self):
        mutations = [
            lambda p, r, c: p.update(number=416),
            lambda p, r, c: p.update(merge_commit_sha="0" * 40),
            lambda p, r, c: p["head"].update(sha="0" * 40),
            lambda p, r, c: r[0].update(commit_id="0" * 40),
            lambda p, r, c: c[0].update(conclusion="failure"),
            lambda p, r, c: c.pop(),
            lambda p, r, c: c.append(c[0]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.validate(mutation)

    def test_rejects_wrong_tree_and_controller(self):
        self.expected[("show", "-s", "--format=%T", bp.S)] = "0" * 40
        with self.assertRaises(ValueError):
            self.validate()
        self.expected[("show", "-s", "--format=%T", bp.S)] = bp.S_TREE
        with self.assertRaises(ValueError):
            bp.validate(Path.cwd(), "0" * 40, bp.REPO, *evidence())

    def test_other_releases_keep_existing_ancestor_gate(self):
        workflow = Path(__file__).parents[4] / ".github/workflows/developer-a-production-release.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("elif [[ \"$action\" != rollback ]]; then", text)
        self.assertIn('git merge-base --is-ancestor "$release_sha" origin/main', text)
        self.assertIn('git -C .provenance-controller fetch --no-tags origin refs/pull/415/head', text)
        self.assertIn("rev-parse FETCH_HEAD)\" = '" + bp.H + "'", text)
        self.assertIn('"$release_sha" = \'766b93faf52e61fb5d65644302633951b594888a\'', text)


if __name__ == "__main__":
    unittest.main()
