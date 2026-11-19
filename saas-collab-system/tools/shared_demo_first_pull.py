"""One-off private collection; run in an isolated service-profile container.

Never imports into a database or changes the shared HTTP application's routing.
Only aggregate progress and a hash receipt are written outside the masked bundle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from contextlib import ExitStack


def private_path(raw, *, directory=False):
    path = Path(raw)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('PRIVATE_PATH_REQUIRED')
    valid = path.is_dir() if directory else path.is_file()
    if not valid or path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid():
        raise ValueError('PRIVATE_PERMISSIONS_REQUIRED')
    return path


def deny_sql(execute, sql, params, many, context):
    raise RuntimeError('DATABASE_ACCESS_FORBIDDEN_DURING_COLLECTION')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--credential-file', required=True)
    parser.add_argument('--masking-file', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--batch', required=True)
    args = parser.parse_args()
    if not args.batch.replace('-', '').isalnum() or len(args.batch) > 80:
        raise ValueError('BATCH_NAME_INVALID')
    credential = json.loads(private_path(args.credential_file).read_text())
    masking = private_path(args.masking_file).read_text().strip()
    root = private_path(args.output_root, directory=True)
    output = root / args.batch
    progress_file = root / (args.batch + '-progress.json')
    if output.exists() or progress_file.exists():
        raise ValueError('NEW_BATCH_REQUIRED')
    os.umask(0o077)
    import django
    django.setup()
    from django.conf import settings
    from django.db import connections
    from apps.demo_sync.pipeline import RESOURCES, build_snapshot
    from apps.demo_sync.service import ReadonlyClient, verified_bundle_files
    if not (settings.DEMO_DATA_SYNC_SERVICE_INSTANCE
            and settings.DATABASES['default']['NAME'].startswith('saas_collab_sync_')
            and not settings.LIVE_PLATFORM_SECURITY_APPROVED
            and not settings.LIVE_READONLY_SYNC_ENABLED
            and not settings.DEMO_DATA_SYNC_IMPORT_ENABLED
            and settings.PLATFORM_NETWORK_MODE == 'mock'
            and settings.LIVE_CUSTODY_BACKEND == 'refuse'
            and not settings.CELERY_BEAT_SCHEDULE):
        raise RuntimeError('ISOLATED_SERVICE_PROFILE_REQUIRED')
    os.environ['MANUAL_DEMO_CLIENT_ID'] = credential['client_id']
    os.environ['MANUAL_DEMO_CLIENT_SECRET'] = credential['client_secret']
    os.environ['MANUAL_DEMO_MASKING_KEY'] = masking
    client = ReadonlyClient({'url': 'https://xtsy.dingfengchuangyu.com',
                             'client_id_env': 'MANUAL_DEMO_CLIENT_ID',
                             'client_secret_env': 'MANUAL_DEMO_CLIENT_SECRET',
                             'masking_key_env': 'MANUAL_DEMO_MASKING_KEY', 'page_size': 100})
    started = time.monotonic()
    progress = {'status': 'collecting', 'batch': args.batch, 'requests': 0,
                'store_ids': [6], 'warehouse_ids': [2], 'tenant_id': 1,
                'order_business_date': '2026-10-22', 'fetched_counts': {},
                'database_imported': False, 'http_switched': False}

    def save():
        progress['requests'] = client.request_count
        progress['elapsed_seconds'] = round(time.monotonic() - started)
        temp = progress_file.with_suffix('.tmp')
        temp.write_text(json.dumps(progress, sort_keys=True))
        os.replace(temp, progress_file)

    original_fetch = client.fetch

    def fetch(resource, params):
        if time.monotonic() - started > 3600 or client.request_count >= 2000:
            raise RuntimeError('MANUAL_COLLECTION_BUDGET_EXCEEDED')
        return original_fetch(resource, params)

    def report(resource, total, count):
        progress['resource'] = resource
        counts = progress['fetched_counts']
        counts[resource] = counts.get(resource, 0) + count
        save()

    client.fetch = fetch
    save()
    try:
        with ExitStack() as stack:
            for alias in connections:
                stack.enter_context(connections[alias].execute_wrapper(deny_sql))
            manifest = build_snapshot(client=client, resources=RESOURCES,
                store_ids=[6], warehouse_ids=[2], date_from='2026-10-22', date_to='2026-10-22',
                output_dir=output, scope_key='1:shared-demo-admin-acceptance', progress=report)
            verified_bundle_files(output)
        progress.update(status='ready', manifest_sha256=hashlib.sha256(
            (output / 'manifest.json').read_bytes()).hexdigest(),
            published_counts={f['resource']: f['count'] for f in manifest['files']},
            consistent=manifest['consistent'], deidentified=manifest['deidentified'])
    except Exception as exc:
        # Do not expose exception text: source/driver errors can contain data.
        progress.update(status='failed', error_type=type(exc).__name__,
                        error_code=getattr(exc, 'code', 'MANUAL_COLLECTION_FAILED'))
        save()
        return 1
    finally:
        client.close()
    save()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('MANUAL_COLLECTION_PREFLIGHT_FAILED', file=sys.stderr)
        sys.exit(2)
