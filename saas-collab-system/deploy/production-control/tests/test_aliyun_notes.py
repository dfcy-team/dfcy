import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('aliyun_notes', Path(__file__).parents[1]/'aliyun_notes.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class IntegrationTests(unittest.TestCase):
    def test_build_forces_production_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'dist').mkdir()
            notes = root/'notes.json'
            notes.write_text('[]')
            (root/'dist/release-notes.json').write_text('[]')
            with patch.object(module, 'FRONTEND', root), patch.object(module, 'NOTES', notes), patch.object(module.subprocess, 'run') as run, patch('sys.argv', ['cmd', 'build', '--version', '2.44.353', '--history', 'history.json']):
                module.main()
                self.assertEqual(run.call_args.kwargs['env']['VITE_USE_MOCK'], 'false')
                self.assertEqual(run.call_args.kwargs['env']['VITE_API_BASE_URL'], '')

    def test_confirm_rejects_failure_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder)/'receipt.json'
            receipt.write_text(json.dumps({'status': 'FAIL', 'version': '2.44.353'}))
            argv = ['cmd', 'confirm', '--version', '2.44.353', '--history', 'history.json', '--deployment-receipt', str(receipt), '--url', 'https://example.org/release-notes.json', '--output', str(Path(folder)/'out.json')]
            with patch.object(module.subprocess, 'run'), patch.object(module.urllib.request, 'urlopen') as fetch, patch('sys.argv', argv):
                with self.assertRaises(ValueError): module.main()
                fetch.assert_not_called()

    def test_confirm_checks_live_bytes_before_finalize(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = root/'receipt.json'
            receipt.write_text(json.dumps({'status': 'PASS', 'version': '2.44.353'}))
            notes = root/'notes.json'
            notes.write_bytes(b'expected')
            argv = ['cmd', 'confirm', '--version', '2.44.353', '--history', 'history.json', '--deployment-receipt', str(receipt), '--url', 'https://example.org/release-notes.json', '--output', str(root/'out.json')]
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'old content'
            with patch.object(module, 'NOTES', notes), patch.object(module.subprocess, 'run') as run, patch.object(module.urllib.request, 'urlopen', return_value=response), patch('sys.argv', argv):
                with self.assertRaises(ValueError): module.main()
                self.assertEqual(run.call_count, 1)
                response.__enter__.return_value.read.return_value = b'expected'
                module.main()
                self.assertIn('finalize', run.call_args.args[0])

if __name__ == '__main__': unittest.main()
