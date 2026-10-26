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
from tests.test_daily_ads_raw_dedup import ads, archive  # noqa: F401

pytestmark = pytest.mark.django_db


def invoke(operation, **kwargs):
    stdout = io.StringIO()
    call_command('raw_oss_backup', operation, stdout=stdout, **kwargs)
    return json.loads(stdout.getvalue())


def test_snapshot_package_and_loader_validation(context, tmp_path, ads):
    _, job = context
    root = tmp_path / 'raw'
    root.mkdir()
    config = {'raw_local': {'BACKEND': 'apps.integrations.raw_local_storage.PrivateRawLocalStorage',
                           'OPTIONS': {'location': str(root), 'namespace': 'backup-test', 'min_free_bytes': 0}}}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job,
                                run_id='oss-backup-proof', idempotency_key='oss-backup-proof')
    adapter = type('Adapter', (), {'adapter_name': 'offline', 'authorization': None})()
    with override_settings(STORAGES=config, RAW_PAYLOAD_STORAGE_ALIAS='raw_local',
                           RAW_PAYLOAD_STORAGE_NAMESPACE='backup-test'):
        entry = archive_raw_page(job, run, adapter, '', {'records': [{'id': 'synthetic'}]})
        with override_settings(RAW_PAYLOAD_STORAGE_ALIAS=''):
            inline = archive_raw_page(job, run, adapter, 'inline', {'records': [{'id': 'history'}]})
            shared = archive(ads)
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
            # Same shared primary key is corrupt in default, intact in snapshot.
            with connection.cursor() as cursor:
                cursor.execute('UPDATE integrations_sharedadvertisingrawpayload SET payload=%s WHERE id=%s',
                               [json.dumps({'corrupt': True}), shared.shared_payload_reference.payload_id])
            manifest = tmp_path / 'refs.jsonl'
            result = invoke('manifest', database='raw_snapshot', database_backup=str(database_backup),
                            snapshot_confirmed=True, output=str(manifest))
            assert result['reference_count'] == 1
            package = tmp_path / 'package'
            invoke('pack', manifest=str(manifest), database_backup=str(database_backup), database='raw_snapshot',
                   snapshot_confirmed=True, namespace='backup-test', output=str(package), min_free_bytes=0)
            result = invoke('verify-database', package=str(package), database_backup=str(database_backup),
                            database='raw_snapshot', snapshot_confirmed=True)
            assert result['database_reference_matches'] == 1
            assert result['loader_checked_rows'] == 3
            with snapshot.cursor() as cursor:
                cursor.execute('UPDATE integrations_syncrawenvelope SET payload=%s WHERE id=%s',
                               [json.dumps({'tampered': True}), inline.pk])
            with pytest.raises(CommandError, match='payload hash mismatch'):
                invoke('verify-database', package=str(package), database_backup=str(database_backup),
                       database='raw_snapshot', snapshot_confirmed=True)
            with snapshot.cursor() as cursor:
                cursor.execute('UPDATE integrations_syncrawenvelope SET payload=%s WHERE id=%s',
                               [json.dumps(inline.payload), inline.pk])
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


def test_manifest_rejects_default_database(tmp_path):
    backup = tmp_path / 'db.sql'
    backup.write_bytes(b'synthetic')
    with pytest.raises(CommandError, match='non-default isolated'):
        invoke('manifest', database='default', database_backup=str(backup),
               snapshot_confirmed=True, output=str(tmp_path / 'refs.jsonl'))
