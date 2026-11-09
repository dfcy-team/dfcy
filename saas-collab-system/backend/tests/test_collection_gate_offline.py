import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
from types import SimpleNamespace


class GateTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / 'apps/integrations/creator_video_capability.py'
        tree = ast.parse(path.read_text())
        self.model = Mock()
        self.ns = dict(ConnectionCapability=self.model, PermissionDenied=PermissionError)
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
                                type_ignores=[]), str(path), 'exec'), self.ns)
        self.auth = SimpleNamespace(pk=36, tenant_id=1, platform='tiktok')

    def test_enabled_requires_exact_source_and_tenant(self):
        self.model.objects.filter.return_value.exists.return_value = True
        self.ns['require_collection_capability'](self.auth, 'VIDEO')
        self.model.objects.filter.assert_called_once_with(authorization_id=36,
            authorization__tenant_id=1, authorization__status='active',
            capability_code='VIDEO', read_enabled=True, status='active', write_enabled=False)

    def test_disabled_or_missing_denies(self):
        self.model.objects.filter.return_value.exists.return_value = False
        for code in ('CREATOR', 'VIDEO'):
            with self.assertRaises(PermissionError):
                self.ns['require_collection_capability'](self.auth, code)

    def test_other_platform_denies_before_query(self):
        self.auth.platform = 'shopee'
        with self.assertRaises(PermissionError):
            self.ns['require_collection_capability'](self.auth, 'VIDEO')
        self.model.objects.filter.assert_not_called()

    def test_unknown_code_denies(self):
        with self.assertRaises(PermissionError):
            self.ns['require_collection_capability'](self.auth, 'ORDER')


if __name__ == '__main__':
    unittest.main()
