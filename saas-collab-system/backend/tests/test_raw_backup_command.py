import io
import json
import sqlite3

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.db.backends.sqlite3._functions import register
from django.test import override_settings

from apps.integrations.models import SyncRun
from apps.integrations.raw_services import archive_raw_page
from tests.test_mock_sync_isolation import context  # noqa: F401

pytestmark = pytest.mark.django_db


def invoke(operation, **kwargs):
    stdout = io.StringIO()
    call_command('raw_local_backup', operation, stdout=stdout, **kwargs)
    return json.loads(stdout.getvalue())


def test_snapshot_backup_and_restored_database_validation(context, tmp_path):
    _, job = context
    root = tmp_path / 'raw'
    root.mkdir(mode=0o700)
    config = {'raw_local': {'BACKEND': 'apps.integrations.raw_local_storage.PrivateRawLocalStorage',
                            'OPTIONS': {'location': str(root), 'namespace': 'backup-test', 'min_free_bytes': 0}}}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job,
                                run_id='backup-proof', idempotency_key='backup-proof')
    adapter = type('Adapter', (), {'adapter_name': 'offline', 'authorization': None})()
    with override_settings(STORAGES=config, RAW_PAYLOAD_STORAGE_ALIAS='raw_local',
                           RAW_PAYLOAD_STORAGE_NAMESPACE='backup-test'):
        entry = archive_raw_page(job, run, adapter, '', {'records': [{'id': 'synthetic'}]})

    # Restore an actual SQL backup into a separate SQLite database. Never point
    # the manifest exporter at the live source when validating a recovery point.
    database_backup = tmp_path / 'snapshot.sql'
    database_backup.write_text('\n'.join(connection.connection.iterdump()), encoding='utf-8')
    snapshot_path = tmp_path / 'restored.sqlite3'
    with sqlite3.connect(snapshot_path) as restored:
        register(restored)
        restored.executescript(database_backup.read_text(encoding='utf-8'))
    snapshot = connection.copy(alias='raw_snapshot')
    snapshot.settings_dict['NAME'] = str(snapshot_path)
    snapshot.ensure_connection()
    connections.databases['raw_snapshot'] = snapshot.settings_dict
    connections['raw_snapshot'] = snapshot
    try:
        manifest = tmp_path / 'refs.jsonl'
        result = invoke('manifest', database='raw_snapshot', snapshot_confirmed=True, output=str(manifest))
        assert result['reference_count'] == 1
        package = tmp_path / 'package'
        invoke('pack', manifest=str(manifest), database_backup=str(database_backup),
               source_root=str(root), namespace='backup-test', output=str(package), min_free_bytes=0)
        result = invoke('verify-database', package=str(package), database_backup=str(database_backup),
                        database='raw_snapshot', snapshot_confirmed=True)
        assert result['database_reference_matches'] == 1
        # Demonstrate that a different restored reference set is not accepted
        # merely because all files already listed in the package remain valid.
        with snapshot.cursor() as cursor:
            cursor.execute('UPDATE integrations_syncrawenvelope SET payload_hash=%s WHERE id=%s',
                           ['0' * 64, entry.pk])
        with pytest.raises(CommandError, match='references do not match'):
            invoke('verify-database', package=str(package), database_backup=str(database_backup),
                   database='raw_snapshot', snapshot_confirmed=True)
    finally:
        snapshot.close()
        del connections['raw_snapshot']
        del connections.databases['raw_snapshot']


def test_manifest_requires_snapshot_confirmation(tmp_path):
    with pytest.raises(CommandError, match='snapshot-confirmed'):
        invoke('manifest', database='default', output=str(tmp_path / 'refs.jsonl'))


def test_manifest_does_not_overwrite(tmp_path):
    target = tmp_path / 'refs.jsonl'
    target.write_text('existing', encoding='utf-8')
    with pytest.raises(CommandError, match='new file'):
        invoke('manifest', database='default', snapshot_confirmed=True, output=str(target))
    assert target.read_text() == 'existing'
