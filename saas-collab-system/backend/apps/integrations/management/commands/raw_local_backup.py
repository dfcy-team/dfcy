"""Explicit, offline snapshot export and local RAW package operations."""
import json
import os
from pathlib import Path
import tempfile
from itertools import zip_longest

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Q

from apps.integrations.models import SyncRawEnvelope


class Command(BaseCommand):
    help = 'Export RAW refs from a restored database snapshot; package or verify local archive files.'

    def add_arguments(self, parser):
        parser.add_argument('operation', choices=['manifest', 'pack', 'verify', 'verify-database', 'archive'])
        parser.add_argument('--database')
        parser.add_argument('--snapshot-confirmed', action='store_true',
                            help='Confirm the database alias points to an isolated restored backup, never live production.')
        parser.add_argument('--output')
        parser.add_argument('--manifest')
        parser.add_argument('--database-backup')
        parser.add_argument('--source-root')
        parser.add_argument('--namespace')
        parser.add_argument('--package')
        parser.add_argument('--min-free-bytes', type=int, default=10737418240)

    def handle(self, *args, **options):
        operation = options['operation']
        if operation == 'manifest':
            return self._manifest(options)
        from apps.integrations.raw_backup import create_backup, verify_backup
        try:
            if operation == 'pack':
                required = ['manifest', 'database_backup', 'source_root', 'namespace', 'output']
                if not all(options.get(name) for name in required):
                    raise CommandError('pack requires manifest, database-backup, source-root, namespace and output.')
                result = create_backup(options['manifest'], options['database_backup'],
                                       options['source_root'], options['namespace'], options['output'],
                                       min_free_bytes=options['min_free_bytes'])
            elif operation == 'archive':
                if not options.get('package') or not options.get('database_backup') or not options.get('output'):
                    raise CommandError('archive requires package, database-backup and output.')
                from apps.integrations.raw_backup_archive import create_archive
                result = create_archive(options['package'], options['database_backup'], options['output'],
                                        min_free_bytes=options['min_free_bytes'])
            else:
                if not options.get('package') or not options.get('database_backup'):
                    raise CommandError('verify requires package and database-backup.')
                result = verify_backup(options['package'], options['database_backup'])
                if operation == 'verify-database':
                    alias = options.get('database')
                    if not alias or not options['snapshot_confirmed'] or alias not in connections:
                        raise CommandError('verify-database requires an isolated restored database and snapshot-confirmed.')
                    fields = ['id', 'raw_ref', 'tenant_id', 'payload_storage_alias', 'payload_object_key', 'payload_hash']
                    rows = (SyncRawEnvelope.objects.using(alias)
                            .filter(Q(payload_storage_alias__isnull=False) | Q(payload_object_key__isnull=False))
                            .order_by('pk').values(*fields).iterator(chunk_size=500))
                    matched = 0
                    with (Path(options['package']) / 'refs.jsonl').open(encoding='utf-8') as source:
                        manifest_rows = (json.loads(line) for line in source)
                        for actual, expected in zip_longest(rows, manifest_rows):
                            if actual != expected:
                                raise CommandError('Restored database references do not match the package manifest.')
                            matched += 1
                    result = {**result, 'database_reference_matches': matched,
                              'snapshot_confirmed_by_operator': True}
        except CommandError:
            raise
        except Exception:
            raise CommandError('RAW backup operation failed; package must not be treated as verified.') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _manifest(self, options):
        alias, output = options.get('database'), options.get('output')
        if not alias or not output or not options['snapshot_confirmed']:
            raise CommandError('manifest requires database, output and snapshot-confirmed; use an isolated restored database.')
        if alias not in connections:
            raise CommandError('Unknown snapshot database alias.')
        path = Path(output)
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise CommandError('Output must be a new file in an existing private directory.')
        fields = ['id', 'raw_ref', 'tenant_id', 'payload_storage_alias', 'payload_object_key', 'payload_hash']
        rows = (SyncRawEnvelope.objects.using(alias)
                .filter(Q(payload_storage_alias__isnull=False) | Q(payload_object_key__isnull=False))
                .order_by('pk').values(*fields).iterator(chunk_size=500))
        temp_path = None
        count = 0
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix='.raw-refs-', delete=False) as target:
                temp_path = Path(target.name)
                os.chmod(temp_path, 0o600)
                for row in rows:
                    if row['payload_storage_alias'] != 'raw_local' or not row['payload_object_key']:
                        raise CommandError('Snapshot contains non-local or incomplete external references; export refused.')
                    target.write(json.dumps(row, ensure_ascii=False) + '\n')
                    count += 1
                target.flush()
                os.fsync(target.fileno())
            os.link(temp_path, path)
        except CommandError:
            raise
        except Exception:
            raise CommandError('Snapshot reference export failed; no successful manifest reported.') from None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self.stdout.write(json.dumps({'status': 'exported', 'reference_count': count,
                                     'snapshot_confirmed_by_operator': True}))
