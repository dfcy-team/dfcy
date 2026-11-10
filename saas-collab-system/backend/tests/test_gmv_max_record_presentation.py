"""Pure presentation contract tests; no provider or database access."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


source = Path(__file__).resolve().parents[1] / 'apps/integrations/gmv_max_records.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
namespace = {}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
    and n.name == 'audit_row'], type_ignores=[]), str(source), 'exec'), namespace)
audit_row = namespace['audit_row']


class GMVMaxPresentationTests(unittest.TestCase):
    def row(self, result, detail):
        return audit_row(SimpleNamespace(pk=2, result=result, masked_detail=detail, created_at=None),
            SimpleNamespace(store_id=3, advertiser_id='123', store=SimpleNamespace(code='TEST', name='Store')))

    def test_snapshot_reuse_is_not_new_business_rows(self):
        row = self.row('success', {'committed': True, 'created': False, 'raw_payload_id': 4})
        self.assertEqual(row['stored_count'], 1)
        self.assertIsNone(row['created_count'])
        self.assertIsNone(row['sync_job_id'])
        self.assertEqual(row['resource_type'], 'gmv_max_report')

    def test_failed_attempt_does_not_claim_zero_or_stored_data(self):
        row = self.row('failed', {'error_type': 'ValidationError'})
        self.assertIsNone(row['stored_count'])
        self.assertIsNone(row['failed_count'])
        self.assertIn('不能据此判定历史数据缺失', row['evidence_note'])

    def test_only_allowlisted_evidence_is_exposed(self):
        row = self.row('success', {'committed': True, 'token': 'synthetic-secret', 'pages': ['private'], 'date': '2026-11-10'})
        self.assertNotIn('token', row['evidence'])
        self.assertNotIn('pages', row['evidence'])
        self.assertEqual(row['evidence']['date'], '2026-11-10')


if __name__ == '__main__':
    unittest.main()
