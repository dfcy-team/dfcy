import ast
from datetime import date, timedelta
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / "apps/integrations/collection_sync.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
namespace = {"ValidationError": ValueError, "timedelta": timedelta}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
    and n.name == "collection_plan"], type_ignores=[]), str(source), "exec"), namespace)
plan = namespace["collection_plan"]


class CollectionPlanTests(unittest.TestCase):
    def test_complete_days_only(self):
        self.assertEqual(plan({"actor_id": 1, "recent_days": 2}, "video_metrics", date(2026, 11, 11))["units"],
                         ["2026-11-09", "2026-11-10"])

    def test_bounded_window(self):
        for days in (0, 3, True, "1"):
            with self.assertRaises(ValueError):
                plan({"actor_id": 1, "recent_days": days}, "video_metrics", date.today())

    def test_unique_explicit_creator_ids(self):
        self.assertEqual(plan({"actor_id": 1, "influencer_ids": [8, 2]}, "creator_profile", date.today())["units"], ["2", "8"])
        for ids in ([], [1, 1], [True], ["1"], list(range(1, 102))):
            with self.assertRaises(ValueError):
                plan({"actor_id": 1, "influencer_ids": ids}, "creator_profile", date.today())

    def test_actor_is_required(self):
        for actor in (None, True, 0, "1"):
            with self.assertRaises(ValueError):
                plan({"actor_id": actor}, "video_metrics", date.today())


if __name__ == "__main__":
    unittest.main()
