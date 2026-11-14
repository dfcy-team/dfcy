"""Pure parser contract checks; never query production or call TikTok."""
import ast
from pathlib import Path
import unittest


source = Path(__file__).resolve().parents[1] / "apps/influencers/tiktok_shop_dataset.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
namespace = {"DatasetError": ValueError}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
    and n.name == "_affiliate_page_records"], type_ignores=[]), str(source), "exec"), namespace)
parse = namespace["_affiliate_page_records"]


class AffiliateEmptyPageTests(unittest.TestCase):
    def test_explicit_zero_without_cursor(self):
        for data in ({"total_count": 0}, {"total_count": 0, "orders": None}):
            self.assertEqual(parse(data, "orders"), [])

    def test_ambiguous_missing_records_fail_closed(self):
        for data in ({}, {"total_count": 2}, {"total_count": "0"},
                     {"total_count": False}, {"total_count": 0, "next_page_token": "next"},
                     {"total_count": 0, "orders": {}}, None):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse(data, "orders")

    def test_real_records_preserved(self):
        rows = [{"id": "test"}]
        self.assertIs(parse({"orders": rows, "total_count": 1}, "orders"), rows)

    def test_page_bound_preserved(self):
        with self.assertRaises(ValueError):
            parse({"orders": [{}] * 51}, "orders")


if __name__ == "__main__":
    unittest.main()
