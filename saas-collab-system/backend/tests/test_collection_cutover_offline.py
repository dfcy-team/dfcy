import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "apps/integrations/collection_cutover.py"
spec = importlib.util.spec_from_file_location("collection_cutover", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.auth = dict(id=10, tenant_id=1, platform="tiktok", status="active",
                         store_id=20, integration_config_id=30, preflight_passed=True)
        self.caps = [dict(tenant_id=1, authorization_id=10, code=code,
                          read_enabled=True, write_enabled=False, status="active")
                     for code in ("CREATOR", "VIDEO")]
        self.job = dict(id=40, tenant_id=1, authorization_id=10,
                        integration_config_id=30, resource_type="video_metrics",
                        scheduler_ready=True, verified_live_run=True, cutover_fence_ready=True)
        self.timer = dict(name="video-nightly", tenant_id=1,
                          subjects=[(20, "video_metrics")], active_run=False)

    def plan(self, **overrides):
        args = dict(tenant_id=1, authorizations=[self.auth], capabilities=self.caps,
                    jobs=[self.job], timers=[self.timer])
        args.update(overrides)
        return module.plan_cutover(**args)

    def test_existing_job_reused_and_new_job_disabled(self):
        result = self.plan()
        self.assertEqual([r["action"] for r in result["jobs"]], ["create_disabled", "reuse"])
        self.assertFalse(result["mutations_performed"])
        self.assertTrue(result["timers"][0]["safe_to_disable"])

    def test_partial_shared_timer_coverage_cannot_stop(self):
        self.timer["subjects"].append((21, "video_metrics"))
        self.assertFalse(self.plan()["timers"][0]["safe_to_disable"])

    def test_inflight_or_unknown_inflight_cannot_stop(self):
        for state in (True, None):
            self.timer["active_run"] = state
            self.assertFalse(self.plan()["timers"][0]["safe_to_disable"])

    def test_missing_cutover_evidence_cannot_stop(self):
        for key in ("scheduler_ready", "verified_live_run", "cutover_fence_ready"):
            job = {**self.job, key: False}
            self.assertFalse(self.plan(jobs=[job])["timers"][0]["safe_to_disable"])

    def test_duplicate_jobs_blocked(self):
        result = self.plan(jobs=[self.job, {**self.job, "id": 41}])
        self.assertEqual(result["jobs"][1]["reason"], "duplicate_jobs")
        self.assertFalse(result["timers"][0]["safe_to_disable"])

    def test_ambiguous_authorization_blocked(self):
        result = self.plan(authorizations=[self.auth, {**self.auth, "id": 11}])
        self.assertTrue(all(r["reason"] == "ambiguous_authorization" for r in result["jobs"]))

    def test_cross_tenant_job_not_reused(self):
        result = self.plan(jobs=[{**self.job, "tenant_id": 2}])
        self.assertEqual(result["jobs"][1]["action"], "create_disabled")
        self.assertFalse(result["timers"][0]["safe_to_disable"])

    def test_disabled_capability_and_failed_preflight_block(self):
        self.assertTrue(all(r["action"] == "blocked" for r in self.plan(capabilities=[])["jobs"]))
        self.auth["preflight_passed"] = False
        self.assertTrue(all(r["reason"] == "preflight_not_passed" for r in self.plan()["jobs"]))

    def test_empty_timer_is_not_verified(self):
        self.timer["subjects"] = []
        self.assertFalse(self.plan()["timers"][0]["safe_to_disable"])

    def test_wrong_configuration_blocked(self):
        self.job["integration_config_id"] = 99
        self.assertEqual(self.plan()["jobs"][1]["reason"], "job_configuration_mismatch")


if __name__ == "__main__":
    unittest.main()
