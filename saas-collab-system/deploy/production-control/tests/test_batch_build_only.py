from pathlib import Path
import unittest


WORKFLOW = (Path(__file__).resolve().parents[4] / ".github" / "workflows"
            / "production-artifacts-build-only.yml").read_text(encoding="utf-8")


class BatchBuildOnlyWorkflowTests(unittest.TestCase):
    def test_v330_uses_configured_source_and_controller_provenance(self):
        self.assertIn("v330-release-identity.json", WORKFLOW)
        self.assertIn('refs/pull/$V330_PR/head', WORKFLOW)
        self.assertIn('[[ "$(git rev-parse FETCH_HEAD)" == "$V330_H" ]]', WORKFLOW)
        self.assertIn("ci/batch_provenance.py", WORKFLOW)
        self.assertIn("validate_v330_controller", WORKFLOW)
        self.assertIn("vars.V330_APPROVED_BUILD_CONTROLLER_SHA", WORKFLOW)
        self.assertIn("pull-requests: read", WORKFLOW)
        self.assertIn('if [[ "$V330_SOURCE" != true ]]; then', WORKFLOW)

    def test_original_main_and_historical_gates_and_manifest_chain_remain(self):
        self.assertIn('git merge-base --is-ancestor "$REQUESTED_SHA" origin/main', WORKFLOW)
        self.assertIn("validate-history", WORKFLOW)
        self.assertIn("Create production-format manifest and build-only receipt", WORKFLOW)
        self.assertIn("production-build-only-${{ needs.validate.outputs.release_sha }}", WORKFLOW)
        self.assertNotIn("deploy:", WORKFLOW)
        self.assertNotIn("ssh", WORKFLOW.lower())


if __name__ == "__main__":
    unittest.main()
