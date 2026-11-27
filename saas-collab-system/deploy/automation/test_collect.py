import unittest
from unittest.mock import patch
import collect

class CollectorTests(unittest.TestCase):
    def test_timestamp(self):
        self.assertEqual(collect.timestamp("Fri 2026-11-27 02:30:00 UTC"), "2026-11-27T02:30:00+00:00")
        self.assertIsNone(collect.timestamp("n/a"))

    def test_service_failure_is_visible(self):
        def props(unit):
            if unit.endswith(".timer"):
                return {"LoadState":"loaded","UnitFileState":"enabled","ActiveState":"active"}
            return {"ActiveState":"failed","Result":"exit-code","ExecMainStatus":"1",
                    "ExecMainStartTimestamp":"Fri 2026-11-27 02:30:00 UTC"}
        with patch.object(collect, "properties", side_effect=props), patch.object(
            collect, "command", return_value="OnCalendar=*-*-* 02:30:00 Asia/Shanghai"):
            rows = collect.collect()["tasks"]
        self.assertEqual(rows[0]["state"], "failed")
        self.assertIn("退出码 1", rows[0]["last_result"])
        self.assertEqual(len(rows), 9)


    def test_bounded_output_discards_oldest_history(self):
        import json
        runs = [dict(id=str(i), status="success", started_at=None,
                     finished_at=f"2026-11-27T00:{i//60:02}:{i%60:02}+00:00",
                     result="结果"*100) for i in range(600)]
        snapshot = {"tasks":[dict(id="abc", runs=runs)]}
        payload = collect.serialize_bounded(snapshot)
        self.assertLessEqual(len(payload), 131072)
        remaining = json.loads(payload)["tasks"][0]["runs"]
        self.assertEqual(remaining[-1]["id"], "599")
        self.assertNotEqual(remaining[0]["id"], "0")

    def test_missing_timer_keeps_enabled_unknown(self):
        with patch.object(collect, "properties", return_value={"LoadState":"not-found"}), patch.object(
            collect, "collect_backend", return_value=([], {})):
            rows = collect.collect()["tasks"]
        self.assertIsNone(rows[0]["enabled"])
        self.assertEqual(rows[0]["state"], "unknown")
        self.assertLessEqual(len(collect.serialize_bounded({"tasks": rows})), 131072)

    def test_beat_uses_beat_container(self):
        calls = []
        def invoke(args):
            calls.append(args)
            return '{"business":{}}' if args[2] == "production-backend-1" else '{}'
        with patch.object(collect, "command", side_effect=invoke), patch.object(
            collect.subprocess, "run", side_effect=OSError()):
            collect.collect_backend("2026-11-27T00:00:00+00:00")
        self.assertEqual(calls[1][2], "production-celery-beat-1")

if __name__ == "__main__":
    unittest.main()
