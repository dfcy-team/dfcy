"""Offline merge invariants, runnable without Django settings or a database."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MainMergeContractTests(unittest.TestCase):
    def test_resource_choices_are_unique_and_keep_both_platforms(self):
        tree = ast.parse((ROOT / "models.py").read_text(encoding="utf-8-sig"))
        job = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SyncJob")
        choices = next(n for n in job.body if isinstance(n, ast.ClassDef) and n.name == "ResourceType")
        values = [n.value.elts[0].value for n in choices.body if isinstance(n, ast.Assign)]
        self.assertEqual(len(values), len(set(values)))
        self.assertIn("affiliate_order", values)
        self.assertIn("advertising_report", values)

    def test_shared_model_classes_are_retained(self):
        tree = ast.parse((ROOT / "models.py").read_text(encoding="utf-8-sig"))
        names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
        self.assertTrue({"AdsOAuthSession", "ShopeeAdvertisingRecord", "HistorySyncTaskControl"} <= names)

    def test_both_slice_wait_contracts_are_retained(self):
        tree = ast.parse((ROOT / "sync_services.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_yield_sync_slice")
        names = {n.arg for n in function.args.kwonlyargs}
        self.assertTrue({"history_wait", "ads_lease_wait", "credential_wait"} <= names)

    def test_merge_depends_on_both_unrenamed_histories(self):
        tree = ast.parse((ROOT / "migrations/0047_merge_tiktok_main_integration.py").read_text())
        deps = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "dependencies" for t in n.targets))
        self.assertEqual(set(ast.literal_eval(deps)), {
            ("integrations", "0046_history_task_controls_detail_state"),
            ("integrations", "0046_syncjob_ads_mapping"),
        })
