"""Offline checks: no production DB or API access."""
import ast
from collections import Counter
from pathlib import Path
import unittest
from unittest.mock import Mock


class NightlyTests(unittest.TestCase):
    def setUp(self):
        self.source = (Path(__file__).parent / 'nightly_worker.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.source)

    def function(self, name, namespace):
        node = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<test>', 'exec'), namespace)
        return namespace[name]

    def test_high_load_stops_before_db(self):
        ns = dict(time=Mock(monotonic=lambda: 1), deadline=100, os=Mock(getloadavg=lambda: (4, 0, 0)))
        with self.assertRaisesRegex(RuntimeError, 'resource_or_runtime_guard'):
            self.function('guard', ns)()

    def test_deadline_stops_before_db(self):
        ns = dict(time=Mock(monotonic=lambda: 101), deadline=100)
        with self.assertRaises(RuntimeError):
            self.function('guard', ns)()

    def creator(self, identifier='123', snapshot=False, market='PH'):
        query = Mock()
        query.filter.return_value.exclude.return_value.exclude.return_value.order_by.return_value = query
        query.values.return_value = [{'influencer_id': 1, 'market': market, 'external_influencer_id': identifier}]
        snapshots = Mock()
        snapshots.filter.return_value.exists.return_value = snapshot
        lookup = Mock(return_value={'status': 'saved', 'snapshot': {'identity_status': 'matched'}})
        ns = dict(available_tiktok_lookup_stores=lambda _: [{'region': 'PH', 'id': 2}],
                  actor=object(), InfluencerProfile=Mock(objects=query),
                  TikTokCreatorProfileSnapshot=Mock(objects=snapshots), lookup_tiktok_creator=lookup,
                  guard=lambda: None, counts=Counter(), report=lambda **_: None, time=Mock())
        self.function('creators', ns)()
        return lookup, ns['counts']

    def test_existing_snapshot_skipped(self):
        lookup, counts = self.creator(snapshot=True)
        lookup.assert_not_called()
        self.assertEqual(counts['already_saved'], 1)

    def test_untrusted_id_skipped(self):
        lookup, counts = self.creator(identifier='nickname')
        lookup.assert_not_called()
        self.assertEqual(counts['untrusted_id_skipped'], 1)

    def test_no_approved_market_skipped(self):
        lookup, counts = self.creator(market='MY')
        lookup.assert_not_called()
        self.assertEqual(counts['no_store'], 1)

    def test_matched_saved_separately(self):
        lookup, counts = self.creator()
        lookup.assert_called_once()
        self.assertEqual(counts['saved'], 1)
        self.assertEqual(counts['matched'], 1)


if __name__ == '__main__':
    unittest.main()
