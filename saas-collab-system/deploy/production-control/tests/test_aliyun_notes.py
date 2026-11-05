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

    def test_reconciliation_arguments_forwarded_for_build_and_confirm(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binding, authorization = root/'binding.json', root/'authorization.json'
            binding.write_text('{}')
            authorization.write_text('{}')
            for command in ('build', 'confirm'):
                argv = ['cmd', command, '--version', '2.44.384', '--history', str(root/'history.json'),
                        '--reconciliation-binding', str(binding), '--reconciliation-authorization', str(authorization)]
                if command == 'confirm':
                    receipt = root/'deployment.json'
                    receipt.write_text(json.dumps({'status': 'FAIL', 'version': '2.44.384'}))
                    argv += ['--deployment-receipt', str(receipt), '--url', 'https://example.org/notes.json', '--output', str(root/'out.json')]
                with patch.object(module, 'FRONTEND', root), patch.object(module, 'NOTES', root/'notes.json'), \
                     patch.object(module.subprocess, 'run') as run, patch.object(module.urllib.request, 'urlopen') as fetch, \
                     patch('sys.argv', argv):
                    (root/'dist').mkdir(exist_ok=True)
                    (root/'dist/release-notes.json').write_bytes(b'[]')
                    (root/'notes.json').write_bytes(b'[]')
                    if command == 'confirm':
                        # The check executes first; a real failed check must prevent receipt/network work.
                        run.side_effect = __import__('subprocess').CalledProcessError(2, 'check')
                        with self.assertRaises(__import__('subprocess').CalledProcessError):
                            module.main()
                        forwarded = run.call_args.args[0]
                        self.assertIn('--reconciliation-binding', forwarded)
                        self.assertIn('--reconciliation-authorization', forwarded)
                        fetch.assert_not_called()
                    else:
                        module.main()
                        forwarded = run.call_args_list[0].args[0]
                        self.assertIn('--reconciliation-binding', forwarded)
                        self.assertIn('--reconciliation-authorization', forwarded)

    def test_missing_reconciliation_argument_rejected_before_check(self):
        with tempfile.TemporaryDirectory() as folder:
            argv = ['cmd', 'build', '--version', '2.44.384', '--history', str(Path(folder)/'history.json'),
                    '--reconciliation-binding', str(Path(folder)/'binding.json')]
            with patch.object(module.subprocess, 'run') as run, patch('sys.argv', argv):
                with self.assertRaises(SystemExit):
                    module.main()
                run.assert_not_called()

    def test_build_check_failure_prevents_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            argv = ['cmd', 'build', '--version', '2.44.384', '--history', str(root/'history.json')]
            with patch.object(module, 'FRONTEND', root), patch.object(module.subprocess, 'run',
                 side_effect=__import__('subprocess').CalledProcessError(2, 'check')) as run, patch('sys.argv', argv):
                with self.assertRaises(__import__('subprocess').CalledProcessError):
                    module.main()
                self.assertEqual(run.call_count, 1)

if __name__ == '__main__': unittest.main()
