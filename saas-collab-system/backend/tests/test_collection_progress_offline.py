"""Isolated query-contract tests without a database or provider calls."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ProgressTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / 'apps/integrations/collection_progress.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        namespace = dict(Count=Mock(), Max=Mock(), Q=Mock())
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
                                type_ignores=[]), str(path), 'exec'), namespace)
        self.progress = namespace['store_collection_progress']
        self.models = types.ModuleType('apps.influencers.models')
        self.creators = self.models.TikTokCreatorProfileSnapshot = Mock()
        self.videos = self.models.TikTokVideoSyncBatch = Mock()
        self.creators.objects.filter.return_value.aggregate.return_value = dict(total=4, matched=2, last='date')
        self.videos.objects.filter.return_value.order_by.return_value.values.return_value = []

    def call(self, **kwargs):
        with patch.dict(sys.modules, {'apps.influencers.models': self.models}):
            return self.progress(tenant_id=1, store_id=9, **kwargs)

    def test_other_platform_has_no_tiktok_rows(self):
        self.assertEqual(self.call(platform='shopee', can_view=True), [])
        self.creators.objects.filter.assert_not_called()

    def test_restricted_rows_do_not_query(self):
        rows = self.call(platform='tiktok', can_view=False)
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]['stored_count'])
        self.creators.objects.filter.assert_not_called()
        self.videos.objects.filter.assert_not_called()

    def test_scope_and_identity_counts(self):
        rows = self.call(platform='tiktok', can_view=True)
        self.creators.objects.filter.assert_called_once_with(tenant_id=1, store_id=9)
        self.videos.objects.filter.assert_called_once_with(tenant_id=1, store_id=9)
        self.assertEqual(rows[0]['stored_count'], 4)
        self.assertEqual(rows[0]['verified_count'], 2)
        self.assertEqual(rows[1]['latest_status'], 'no_records')
        self.assertEqual(rows[0]['scheduler_status'], 'unknown')

    def test_failed_batch_count_is_not_claimed_as_committed(self):
        self.videos.objects.filter.return_value.order_by.return_value.values.return_value = [
            dict(status='failed', video_count=50, updated_at='date')]
        rows = self.call(platform='tiktok', can_view=True)
        self.assertIsNone(rows[1]['stored_count'])
        self.assertEqual(rows[1]['latest_status'], 'failed')


if __name__ == '__main__':
    unittest.main()
