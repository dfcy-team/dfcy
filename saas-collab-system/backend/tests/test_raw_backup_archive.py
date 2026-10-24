import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from unittest import mock
from django.core.management import call_command

from apps.integrations.raw_backup import RawBackupError, create_backup
from apps.integrations import raw_backup_archive as archive_module
from apps.integrations.raw_backup_archive import create_archive


class RawBackupArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.db = os.path.join(self.root, 'snapshot.sql.gz')
        with open(self.db, 'wb') as stream:
            stream.write(gzip.compress(b'synthetic SQL snapshot', mtime=0))
        self.source = os.path.join(self.root, 'source')
        os.makedirs(os.path.join(self.source, 'raw', 'unit', 'tenant-1'))
        payload = b'{"ok":true}'
        self.key = 'raw/unit/tenant-1/0123456789abcdef0123456789abcdef.json.gz'
        self.object = os.path.join(self.source, *self.key.split('/'))
        with open(self.object, 'wb') as stream:
            stream.write(gzip.compress(payload, mtime=0))
        self.manifest = os.path.join(self.root, 'refs.jsonl')
        row = {'id': 1, 'raw_ref': 'r', 'tenant_id': 1, 'payload_storage_alias': 'raw_local',
               'payload_object_key': self.key, 'payload_hash': hashlib.sha256(payload).hexdigest()}
        with open(self.manifest, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
        self.package = os.path.join(self.root, 'package')
        create_backup(self.manifest, self.db, self.source, 'unit', self.package, min_free_bytes=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_archive_contents_hashes_and_private_permissions(self):
        output = os.path.join(self.root, 'bundle.tgz')
        result = create_archive(self.package, self.db, output, min_free_bytes=0)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['reference_count'], 1)
        with tarfile.open(output, 'r:gz') as archive:
            self.assertEqual(set(archive.getnames()), {'database.sql.gz', 'raw-package',
                'raw-package/receipt.json', 'raw-package/refs.jsonl', 'raw-package/objects',
                'raw-package/objects/raw', 'raw-package/objects/raw/unit',
                'raw-package/objects/raw/unit/tenant-1',
                'raw-package/objects/' + self.key})
            self.assertEqual(archive.extractfile('database.sql.gz').read(), open(self.db, 'rb').read())
        if os.name != 'nt':
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o600)
        self.assertEqual(os.path.getsize(output), result['bytes'])
        self.assertEqual(archive_module._hash_file(output)[1], result['archive_sha256'])

    def test_refuses_bad_inputs_existing_output_and_low_space(self):
        wrong_db = os.path.join(self.root, 'wrong.sql')
        with open(wrong_db, 'wb') as stream:
            stream.write(b'wrong SQL')
        with self.assertRaisesRegex(RawBackupError, 'SHA256'):
            create_archive(self.package, wrong_db, os.path.join(self.root, 'wrong.tgz'), 0)
        packaged_object = os.path.join(self.package, 'objects', *self.key.split('/'))
        with open(packaged_object, 'wb') as stream:
            stream.write(b'bad gzip')
        with self.assertRaises(RawBackupError):
            create_archive(self.package, self.db, os.path.join(self.root, 'bad.tgz'), 0)
        with open(packaged_object, 'wb') as stream:
            stream.write(gzip.compress(b'{"ok":true}', mtime=0))
        out = os.path.join(self.root, 'exists.tgz')
        with open(out, 'wb') as stream:
            stream.write(b'keep')
        with self.assertRaisesRegex(RawBackupError, 'already exists'):
            create_archive(self.package, self.db, out, 0)
        with mock.patch.object(archive_module.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaisesRegex(RawBackupError, 'Insufficient'):
                create_archive(self.package, self.db, os.path.join(self.root, 'low.tgz'), 1)

    def test_source_change_during_archive_leaves_no_final_file(self):
        output = os.path.join(self.root, 'changed.tgz')
        original = archive_module._snapshot_tree
        changed = False
        def snapshot_then_change(path):
            nonlocal changed
            result = original(path)
            if path == self.package and not changed:
                changed = True
                packaged_object = os.path.join(self.package, 'objects', *self.key.split('/'))
                with open(packaged_object, 'ab') as stream:
                    stream.write(b'x')
            return result
        with mock.patch.object(archive_module, '_snapshot_tree', side_effect=snapshot_then_change):
            with self.assertRaises(RawBackupError):
                create_archive(self.package, self.db, output, 0)
        self.assertFalse(os.path.lexists(output))

    def test_rejects_truncated_trailer_and_bad_crc_without_publishing(self):
        original = archive_module._validate_gzip
        for suffix, mutate in (
            ('truncated', lambda data: data[:-8]),
            ('bad-crc', lambda data: data[:-8] + bytes([data[-8] ^ 1]) + data[-7:]),
        ):
            output = os.path.join(self.root, suffix + '.tgz')
            def corrupt_then_validate(path, mutation=mutate):
                with open(path, 'rb') as stream:
                    data = stream.read()
                with open(path, 'wb') as stream:
                    stream.write(mutation(data))
                return original(path)
            with mock.patch.object(archive_module, '_validate_gzip', side_effect=corrupt_then_validate):
                with self.assertRaisesRegex(RawBackupError, 'gzip stream'):
                    create_archive(self.package, self.db, output, 0)
            self.assertFalse(os.path.lexists(output))

    def test_removes_output_if_post_publication_check_fails(self):
        output = os.path.join(self.root, 'post-publish-failure.tgz')
        original = archive_module._hash_file
        def fail_published_read(path, signature=None):
            if path == output:
                raise OSError('injected readback failure')
            return original(path, signature)
        with mock.patch.object(archive_module, '_hash_file', side_effect=fail_published_read):
            with self.assertRaisesRegex(RawBackupError, 'Archive creation failed'):
                create_archive(self.package, self.db, output, 0)
        self.assertFalse(os.path.lexists(output))

    def test_management_command_dispatches_archive(self):
        output = os.path.join(self.root, 'command-bundle.tgz')
        stdout = io.StringIO()
        call_command('raw_local_backup', 'archive', package=self.package,
                     database_backup=self.db, output=output, min_free_bytes=0, stdout=stdout)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(os.path.isfile(output))


if __name__ == '__main__':
    unittest.main()
