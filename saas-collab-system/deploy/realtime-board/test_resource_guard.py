import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import resource_guard as rg


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name) / "config.json"
        self.state = Path(self.tmp.name) / "state.json"
        self.write_config()
        self.inventory = {"production-celery-1": {"id": "id1", "cpuset": "", "shares": 1024}}
        self.updates = []
        self.lock_patch = patch.object(rg, "deploy_lock")
        cm = self.lock_patch.start()
        cm.return_value.__enter__.return_value = True
        self.addCleanup(self.lock_patch.stop)
        self.inspect_patch = patch.object(rg, "inspect", side_effect=self.fake_inspect)
        self.inspect_patch.start()
        self.addCleanup(self.inspect_patch.stop)
        self.update_patch = patch.object(rg, "update", side_effect=self.fake_update)
        self.update_patch.start()
        self.addCleanup(self.update_patch.stop)
        self.cpu_patch = patch.object(rg.os, "cpu_count", return_value=2)
        self.cpu_patch.start()
        affinity = patch.object(rg.os, "sched_getaffinity", return_value={0, 1}, create=True)
        affinity.start()
        self.addCleanup(affinity.stop)
        self.addCleanup(self.cpu_patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, names=None):
        self.config.write_text(json.dumps({"enabled": True, "containers": names or ["production-celery-1"], "cpuset": "1", "cpu_shares": 256}))

    def fake_inspect(self, name):
        return self.inventory.get(name)

    def fake_update(self, cid, cpuset, shares):
        self.updates.append((cid, cpuset, shares))
        for item in self.inventory.values():
            if item["id"] == cid:
                item["cpuset"], item["shares"] = cpuset, shares
                return True
        return False

    def when(self, hour):
        return datetime(2026, 11, 17, hour, 0, tzinfo=rg.ZoneInfo("Asia/Shanghai"))

    def test_window_boundaries(self):
        self.assertFalse(rg.in_work_window(self.when(8)))
        self.assertTrue(rg.in_work_window(self.when(9)))
        self.assertTrue(rg.in_work_window(self.when(18)))
        self.assertFalse(rg.in_work_window(self.when(19)))

    def test_apply_once_and_restore(self):
        rg.run(self.config, self.state, now=self.when(10))
        rg.run(self.config, self.state, now=self.when(10))
        self.assertEqual(self.updates, [("id1", "1", 256)])
        rg.run(self.config, self.state, now=self.when(20))
        self.assertEqual(self.updates[-1], ("id1", "0,1", 1024))
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_zero_shares_restores_explicit_default(self):
        self.inventory["production-celery-1"]["shares"] = 0
        rg.run(self.config, self.state, now=self.when(10))
        rg.run(self.config, self.state, now=self.when(20))
        self.assertEqual(self.updates[-1], ("id1", "0,1", 1024))
        self.assertEqual(json.loads(self.state.read_text()), {})

    def test_successful_noop_does_not_discard_restore_state(self):
        rg.run(self.config, self.state, now=self.when(10))
        with patch.object(rg, "update", return_value=True):
            self.assertEqual(rg.run(self.config, self.state, now=self.when(20)), 1)
        self.assertIn("production-celery-1", json.loads(self.state.read_text()))

    def test_recreation_does_not_restore_old_snapshot_to_new_id(self):
        rg.run(self.config, self.state, now=self.when(10))
        self.inventory["production-celery-1"] = {"id": "id2", "cpuset": "", "shares": 512}
        rg.run(self.config, self.state, now=self.when(20))
        self.assertEqual(self.updates, [("id1", "1", 256)])

    def test_external_edit_is_preserved_on_restore(self):
        rg.run(self.config, self.state, now=self.when(10))
        self.inventory["production-celery-1"]["shares"] = 700
        rg.run(self.config, self.state, now=self.when(20))
        self.assertEqual(len(self.updates), 1)
        self.assertEqual(self.inventory["production-celery-1"]["shares"], 700)

    def test_busy_lock_is_clean_skip(self):
        cm = rg.deploy_lock
        cm.return_value.__enter__.return_value = False
        out = __import__("io").StringIO()
        with patch("sys.stdout", out):
            self.assertEqual(rg.run(self.config, self.state, now=self.when(10)), 0)
        cm.return_value.__enter__.return_value = True
        self.assertEqual(out.getvalue().strip(), "SKIPPED_LOCKED")
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
