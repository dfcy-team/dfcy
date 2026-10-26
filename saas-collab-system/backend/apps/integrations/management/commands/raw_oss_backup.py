"""Offline restored-snapshot backup workflow; never starts a database restore."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from itertools import zip_longest

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Q

from apps.integrations.models import SyncRawEnvelope
from apps.integrations.raw_backup import _sha256_file, _ordinary_file

FIELDS = ['id', 'raw_ref', 'tenant_id', 'payload_storage_alias', 'payload_object_key', 'payload_hash']


def snapshot_rows(alias, confirmed):
    if not confirmed or not alias or alias == 'default' or alias not in connections:
        raise CommandError('An explicit non-default isolated restored database and snapshot-confirmed are required.')
    selected, default = connections[alias].settings_dict, connections['default'].settings_dict
    if all(str(selected.get(k, '')) == str(default.get(k, '')) for k in ('ENGINE', 'HOST', 'PORT', 'NAME')):
        raise CommandError('Snapshot database must not point to the default database.')
    return (SyncRawEnvelope.objects.using(alias)
            .filter(Q(payload_storage_alias__isnull=False) | Q(payload_object_key__isnull=False))
            .order_by('pk').values(*FIELDS, 'payload').iterator(chunk_size=250))


def clean_row(row):
    row = dict(row)
    if row.pop('payload') != {}:
        raise CommandError('External RAW has inconsistent inline payload.')
    if row['payload_storage_alias'] not in ('raw_local', 'raw_oss') or not row['payload_object_key']:
        raise CommandError('Unknown or incomplete external reference.')
    return row


def compare_database(manifest, alias, confirmed):
    count = 0
    with Path(manifest).open('rb') as stream:
        def lines():
            while True:
                line = stream.readline(1024 * 1024 + 1)
                if not line:
                    return
                if len(line) > 1024 * 1024:
                    raise CommandError('Manifest row too large.')
                yield json.loads(line)
        rows = (clean_row(row) for row in snapshot_rows(alias, confirmed))
        for actual, expected in zip_longest(rows, lines()):
            if actual != expected:
                raise CommandError('Database references do not match manifest.')
            count += 1
    return count


class Command(BaseCommand):
    help = 'Offline RAW OSS paired backup: manifest, pack, verify, publish, fetch, restore-objects, verify-database, retention.'

    def add_arguments(self, parser):
        parser.add_argument('operation', choices=['manifest', 'pack', 'verify', 'publish', 'fetch', 'restore-objects', 'verify-database', 'retention'])
        for name in ('database', 'database-backup', 'manifest', 'namespace', 'output', 'package', 'backup-config', 'source-bucket', 'backup-id'):
            parser.add_argument('--' + name)
        parser.add_argument('--packages', nargs='*')
        parser.add_argument('--snapshot-confirmed', action='store_true')
        parser.add_argument('--isolated-target-confirmed', action='store_true')
        parser.add_argument('--min-free-bytes', type=int, default=10737418240)

    def handle(self, *args, **o):
        from apps.integrations.raw_oss_backup import create_package, verify_package, restore_objects, retention_report
        from apps.integrations.raw_oss_backup_transport import OSSBackupStore, publish_package, fetch_package
        def require(*names):
            if any(not o.get(n) for n in names):
                raise CommandError('Missing required arguments: ' + ', '.join(names))
        def backup_store():
            require('backup_config')
            p = Path(o['backup_config'])
            info = _ordinary_file(p, 'Backup config')
            if info.st_size > 16384:
                raise CommandError('Backup config exceeds limit.')
            config = json.loads(p.read_text())
            if set(config) != {'bucket', 'region', 'endpoint', 'credential_file'}:
                raise CommandError('Backup config must contain only bucket, region, endpoint and credential_file.')
            return OSSBackupStore(**config)
        try:
            operation = o['operation']
            if operation == 'manifest':
                require('database_backup', 'output', 'database')
                output = Path(o['output'])
                receipt = Path(str(output) + '.snapshot.json')
                if output.exists() or output.is_symlink() or receipt.exists() or receipt.is_symlink():
                    raise CommandError('Manifest and receipt must be new files.')
                dbhash = _sha256_file(o['database_backup'], 'Database backup')
                fd, name = tempfile.mkstemp(prefix='.raw-refs-', dir=output.parent)
                count = 0
                try:
                    with os.fdopen(fd, 'wb') as dest:
                        os.chmod(name, 0o600)
                        for row in snapshot_rows(o['database'], o['snapshot_confirmed']):
                            dest.write((json.dumps(clean_row(row), sort_keys=True) + '\n').encode())
                            count += 1
                        dest.flush()
                        os.fsync(dest.fileno())
                    if dbhash != _sha256_file(o['database_backup'], 'Database backup'):
                        raise CommandError('Database backup changed.')
                    os.link(name, output)
                    binding = {'database_sha256': dbhash, 'manifest_sha256': _sha256_file(output, 'Manifest'),
                               'reference_count': count, 'restored_from_backup_confirmed_by_operator': True}
                    with receipt.open('x', encoding='utf-8') as dest:
                        os.chmod(receipt, 0o600)
                        json.dump(binding, dest)
                finally:
                    Path(name).unlink(missing_ok=True)
                result = {'status': 'manifest_exported', 'reference_count': count}
            elif operation == 'pack':
                require('manifest', 'database_backup', 'namespace', 'output', 'database')
                receipt = Path(str(o['manifest']) + '.snapshot.json')
                if _ordinary_file(receipt, 'Snapshot receipt').st_size > 16384:
                    raise CommandError('Snapshot receipt exceeds limit.')
                binding = json.loads(receipt.read_text())
                if (binding.get('database_sha256') != _sha256_file(o['database_backup'], 'Database backup')
                        or binding.get('manifest_sha256') != _sha256_file(o['manifest'], 'Manifest')):
                    raise CommandError('Database/manifest binding mismatch.')
                count = compare_database(o['manifest'], o['database'], o['snapshot_confirmed'])
                if count != binding.get('reference_count'):
                    raise CommandError('Reference count mismatch.')
                readers = {}
                for alias in ('raw_local', 'raw_oss'):
                    if alias not in settings.STORAGES:
                        continue
                    storage = storages[alias]
                    if alias == 'raw_oss':
                        stream_store = object.__new__(OSSBackupStore)
                        stream_store.storage, stream_store.bucket = storage, storage.bucket
                        readers[alias] = stream_store.open
                    else:
                        readers[alias] = lambda key, s=storage: s.open(key, 'rb')
                result = create_package(o['manifest'], o['database_backup'], o['namespace'], o['output'], readers, min_free_bytes=o['min_free_bytes'])
            elif operation == 'verify':
                require('package')
                result = verify_package(o['package'])
            elif operation == 'publish':
                require('package', 'source_bucket')
                configured = settings.STORAGES.get('raw_oss', {}).get('OPTIONS', {}).get('bucket')
                if not configured or configured != o['source_bucket']:
                    raise CommandError('Source bucket must match configured raw_oss bucket.')
                result = publish_package(o['package'], backup_store(), configured)
            elif operation == 'fetch':
                require('backup_id', 'output')
                result = fetch_package(o['backup_id'], backup_store(), o['output'], o['min_free_bytes'])
            elif operation == 'restore-objects':
                require('package', 'source_bucket')
                if not o['isolated_target_confirmed']:
                    raise CommandError('Explicit isolated target confirmation required.')
                target = storages['raw_oss']
                if target.bucket == o['source_bucket']:
                    raise CommandError('Restore target must differ from original source bucket.')
                def writer(alias):
                    def write(key, source):
                        storage = storages[alias]
                        if alias == 'raw_oss' and storage.bucket == o['source_bucket']:
                            raise CommandError('Restore target must be isolated.')
                        with Path(source).open('rb') as f:
                            data = f.read(32 * 1024 * 1024 + 1)
                        if len(data) > 32 * 1024 * 1024:
                            raise CommandError('Restore object exceeds limit.')
                        if storage.save(key, ContentFile(data)) != key:
                            raise CommandError('Restore changed object key.')
                        with storage.open(key, 'rb') as f:
                            actual = f.read(len(data) + 1)
                        if hashlib.sha256(actual).digest() != hashlib.sha256(data).digest():
                            raise CommandError('Restore readback mismatch.')
                    return write
                restored = restore_objects(o['package'], {a: writer(a) for a in ('raw_local', 'raw_oss') if a in settings.STORAGES})
                result = {'status': 'objects_restored', 'object_count': restored}
            elif operation == 'verify-database':
                require('package', 'database', 'database_backup')
                result = verify_package(o['package'])
                if result['database_backup_sha256'] != _sha256_file(o['database_backup'], 'Restored database backup'):
                    raise CommandError('Restored database backup does not match package.')
                count = compare_database(Path(o['package']) / 'refs.jsonl', o['database'], o['snapshot_confirmed'])
                from apps.integrations.raw_services import load_raw_payload, payload_digest
                checked = 0
                # Actual loader covers inline history, shared advertising references and both external aliases.
                for row in SyncRawEnvelope.objects.using(o['database']).order_by('pk').iterator(chunk_size=100):
                    payload = load_raw_payload(row)
                    if not isinstance(payload, dict) or payload_digest(payload) != row.payload_hash:
                        raise CommandError('Restored RAW payload hash mismatch.')
                    checked += 1
                result = {**result, 'database_reference_matches': count, 'loader_checked_rows': checked}
            else:
                result = retention_report(o.get('packages') or [], days=30)
        except CommandError:
            raise
        except Exception:
            raise CommandError('OSS paired backup failed; no successful recovery may be claimed.') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False))
