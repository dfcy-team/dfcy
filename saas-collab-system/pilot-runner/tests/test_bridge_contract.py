from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT.parent / "deploy" / "pilot" / "runner" / "bin" / "runner-action-common.sh").read_text(encoding="utf-8")
INSTALL = (ROOT.parent / "deploy" / "pilot" / "runner" / "install-runner.sh").read_text(encoding="utf-8")
CONFIG = (ROOT.parent / "pilot-runner" / "config.example.json").read_text(encoding="utf-8")


class BridgeContractTests(unittest.TestCase):
    def test_bridge_is_generic_and_uses_the_approved_candidate_path(self):
        self.assertIn("/etc/saas-collab/runner/approved-candidate.json", BRIDGE)
        self.assertNotIn("v24459", BRIDGE.lower())
        self.assertNotIn("release-v2.44.59", BRIDGE)
        self.assertIn("CANDIDATE_MANIFEST_SHA", BRIDGE)

    def test_deploy_and_rollback_bind_to_the_right_ledger_state(self):
        self.assertIn("validate_deploy_binding", BRIDGE)
        self.assertIn('CANDIDATE_PARENT_SHA" = "$current_sha"', BRIDGE)
        self.assertIn("validate_rollback_binding", BRIDGE)
        self.assertIn('CANDIDATE_RELEASE_SHA" = "$current_sha"', BRIDGE)
        self.assertIn('CANDIDATE_PARENT_SHA" = "$previous_sha"', BRIDGE)
        self.assertIn('secure_file "$CONTROL_ROOT/previous.json" previous-ledger', BRIDGE)

    def test_recovery_has_an_independent_current_ledger_path(self):
        start = BRIDGE.index("run_recovery()")
        end = BRIDGE.index("run_rollback()")
        recovery = BRIDGE[start:end]
        self.assertIn("validate_recovery_binding", recovery)
        self.assertNotIn("load_manifest", recovery)

    def test_bridges_do_not_accept_arguments_or_shell_interpolation(self):
        self.assertIn('[[ "$#" -eq 0 ]]', BRIDGE)
        self.assertIn("--registry-token-stdin", BRIDGE)
        self.assertNotIn("eval ", BRIDGE)
        self.assertNotIn("shell=True", BRIDGE)

    def test_runner_sudo_policy_grants_only_no_argument_wrappers(self):
        self.assertIn('"/usr/bin/sudo",', CONFIG)
        self.assertIn('"-n",', CONFIG)
        self.assertIn('"pilot":', CONFIG)
        self.assertIn('"controlled-pilot":', CONFIG)
        self.assertIn('"demo-app":', CONFIG)
        self.assertIn('"synthetic":', CONFIG)
        self.assertIn("saas-collab-pilot-runner-deploy, /usr/local/sbin/saas-collab-pilot-runner-recovery, /usr/local/sbin/saas-collab-pilot-runner-rollback", INSTALL)
        self.assertNotIn("SAAS_COLLAB_PILOT_RUNNER =", INSTALL)
        self.assertNotIn("production-deploy *", INSTALL)

    def test_registry_credential_stays_root_only(self):
        self.assertIn("registry token group must be root", BRIDGE)
        self.assertIn('regular_file "$REGISTRY_TOKEN_FILE" registry-token \'400,600\' root root', (ROOT.parent / "deploy" / "pilot" / "runner" / "preflight-runner.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
