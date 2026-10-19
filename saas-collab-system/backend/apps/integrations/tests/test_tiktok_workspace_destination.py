"""Pure workspace routing regressions; no Django, network or database needed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class WorkspaceDestinationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse((Path(__file__).resolve().parents[1] / "workspace_service.py").read_text(encoding="utf-8-sig"))
        nodes = [node for node in cls.tree.body if (
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RESOURCE_DESTINATIONS" for t in node.targets)
        ) or (isinstance(node, ast.FunctionDef) and node.name == "_resource_destination")]
        cls.namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "workspace-destination-probe", "exec"), cls.namespace)

    def destination(self, resource="advertising_report", mapping=None, fallback=("fallback", "fallback")):
        return self.namespace["_resource_destination"](SimpleNamespace(resource_type=resource, ads_mapping_id=mapping), fallback)

    def test_tiktok_mapping_has_tiktok_destination(self):
        self.assertEqual(self.destination(mapping=7), ("TikTok Ads campaign spend", "integrations_tiktokadsdailyspend"))

    def test_shopee_without_mapping_keeps_main_destination(self):
        self.assertEqual(self.destination(), self.namespace["RESOURCE_DESTINATIONS"]["advertising_report"])
        self.assertEqual(self.destination()[1], "shopee_advertising_record")

    def test_resource_dictionary_has_no_duplicate_keys(self):
        mapping = next(node.value for node in self.tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "RESOURCE_DESTINATIONS" for t in node.targets))
        keys = [ast.literal_eval(key) for key in mapping.keys]
        self.assertEqual(len(keys), len(set(keys)))

    def test_non_ads_and_unknown_resources_keep_original_behavior(self):
        self.assertEqual(self.destination(resource="sales_order", mapping=7), self.namespace["RESOURCE_DESTINATIONS"]["sales_order"])
        self.assertEqual(self.destination(resource="unknown"), ("fallback", "fallback"))

    def test_job_and_run_rows_use_subject_aware_destination(self):
        for name in ("_job_row", "_run_rows"):
            function = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                                and node.func.id == "_resource_destination" for node in ast.walk(function)))
