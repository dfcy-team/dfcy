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
        # V384 already has its own provenance check on protected main; V388
        # must NOT join either legacy exception to the general check-run gate.
        self.assertIn('if [[ "$V330_SOURCE" != true && "$V384_CLOUD_SOURCE" != true ]]; then', WORKFLOW)
        v388 = WORKFLOW.split('elif [[ "$REQUESTED_SHA" == \'d477e713c604cbcd9db0c92fbd1d0bf74e5bb38b\' ]]; then', 1)[1].split('elif [[', 1)[0]
        self.assertNotIn('V330_SOURCE=true', v388)
        self.assertNotIn('V384_CLOUD_SOURCE=true', v388)
        self.assertIn('verify_v388_cloud_source.py "$REQUESTED_SHA"', v388)
        self.assertIn('"$REQUESTED_VERSION" == \'2.44.388\'', v388)
        self.assertIn('"$GITHUB_SHA" == "$(git rev-parse origin/main)"', v388)

    def test_v388_synthetic_plugin_is_limited_to_sales_and_never_packaged(self):
        before, rest = WORKFLOW.split('\n  mysql-sales:\n', 1)
        sales, after = rest.split('\n  mysql-sync-workspace:\n', 1)
        self.assertNotIn('v388_sales_mysql_fixture', before + after)
        self.assertIn('sales_plugin=scripts.sales_mysql_fixture', sales)
        self.assertIn('if [[ "$SOURCE_SHA" == \'d477e713c604cbcd9db0c92fbd1d0bf74e5bb38b\' ]]; then', sales)
        self.assertIn('6b86292d02890b80ee11f7a29d82c3d2ae6466429d855c2eef11a2c2eeb98072', sales)
        self.assertEqual(sales.count('-p "$sales_plugin"'), 2)
        self.assertIn('sha256sum --check --strict', sales)
        self.assertIn('sales_mysql_index_probe', sales)
        self.assertIn('8ed4a62546bb98cb1b17fd448e51258625a7d080360339e4e06bbd1c957e308e', after)

    def test_original_main_and_historical_gates_and_manifest_chain_remain(self):
        self.assertIn('git merge-base --is-ancestor "$REQUESTED_SHA" origin/main', WORKFLOW)
        self.assertIn("validate-history", WORKFLOW)
        self.assertIn("Create production-format manifest and build-only receipt", WORKFLOW)
        self.assertIn("production-build-only-${{ needs.validate.outputs.release_sha }}", WORKFLOW)
        self.assertNotIn("deploy:", WORKFLOW)
        self.assertNotIn("ssh", WORKFLOW.lower())


if __name__ == "__main__":
    unittest.main()
