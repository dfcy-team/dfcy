"""Offline first-batch import into a new private MySQL container, never pilot."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from decimal import Decimal


def main():
    os.umask(0o077)
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.db.models import Sum
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    from apps.commerce.models import SalesOrder, SalesOrderItem, InventorySnapshot
    from apps.demo_sync.importer import import_snapshot
    from apps.demo_sync.shared_readiness import inspect_shared_snapshot
    from shared_demo_first_pull import private_path

    expected_db = 'saas_collab_demo_shared_20261023_a1'
    if settings.DATABASES['default']['NAME'] != expected_db or not settings.DEMO_SHARED_SNAPSHOT_INSTANCE:
        raise RuntimeError('ISOLATED_TARGET_REQUIRED')
    root = private_path('/artifacts', directory=True)
    state = {'status': 'waiting_database', 'database': expected_db, 'http_switched': False}

    def save():
        temp = root / 'db-stage.tmp'
        temp.write_text(json.dumps(state, sort_keys=True))
        os.replace(temp, root / 'db-stage.json')

    save()
    for _ in range(60):
        try:
            with connection.cursor() as c:
                c.execute('SELECT DATABASE()')
                if c.fetchone()[0] != expected_db:
                    raise RuntimeError('ACTUAL_TARGET_MISMATCH')
            break
        except Exception:
            connection.close()
            time.sleep(2)
    else:
        raise RuntimeError('TARGET_DATABASE_NOT_READY')
    state['status'] = 'migrating'
    save()
    call_command('migrate', interactive=False, verbosity=0)
    if CustomUser.objects.exists() or Tenant.objects.exists():
        raise RuntimeError('FRESH_BOOTSTRAP_REQUIRED')
    admin = json.loads(private_path('/run/demo-bootstrap.json').read_text())
    if not (admin['id'] == 1 and admin['tenant_id'] == 1 and admin['username'] == 'root'
            and admin['is_active'] and admin['is_superuser'] and admin['user_type'] == 'internal'):
        raise RuntimeError('APPROVED_ADMIN_REQUIRED')
    with transaction.atomic():
        Tenant.objects.create(pk=1, name='Shared Demo administrator acceptance', code='shared-demo-admin')
        CustomUser.objects.create(**admin)
    state.update(status='waiting_snapshot', admin_count=1)
    save()
    progress_path = root / 'first-real-20261022-a1-progress.json'
    for _ in range(1800):
        p = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        if p.get('status') == 'failed':
            raise RuntimeError('SNAPSHOT_COLLECTION_FAILED')
        if p.get('status') == 'ready':
            break
        time.sleep(2)
    else:
        raise RuntimeError('SNAPSHOT_WAIT_BUDGET_EXCEEDED')
    bundle = root / 'first-real-20261022-a1'
    digest = hashlib.sha256((bundle / 'manifest.json').read_bytes()).hexdigest()
    if digest != p['manifest_sha256']:
        raise RuntimeError('PUBLISHED_MANIFEST_MISMATCH')
    state.update(status='importing', manifest_sha256=digest)
    save()
    # Only this offline process may import. The shared HTTP profile remains closed.
    settings.DEMO_DATA_SYNC_IMPORT_ENABLED = True
    try:
        preview = import_snapshot(bundle, tenant_id=1, actor_id=1, dry_run=True)
        imported = import_snapshot(bundle, tenant_id=1, actor_id=1, dry_run=False)
    finally:
        settings.DEMO_DATA_SYNC_IMPORT_ENABLED = False
    report = inspect_shared_snapshot(bundle, 1, digest, [1])
    if report['errors']:
        raise RuntimeError('SHARED_READINESS_REJECTED')
    checks = 0
    for resource, model, fields, group in (
        ('sales_orders', SalesOrder, ('order_total_amount',), 'currency'),
        ('sales_order_items', SalesOrderItem, ('quantity', 'line_total_amount'), 'currency'),
        ('inventory_snapshots', InventorySnapshot, ('available_qty', 'reserved_qty'), None),
    ):
        source = {}
        with (bundle / (resource + '.jsonl')).open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                key = row.get(group, '') if group else ''
                values = source.setdefault(key, {f: Decimal(0) for f in fields})
                for field in fields:
                    if row.get(field) is not None:
                        values[field] += Decimal(str(row[field]))
        qs = model.objects.all()
        for key, values in source.items():
            q = qs.filter(**{group: key}) if group else qs
            actual = q.aggregate(**{f: Sum(f) for f in fields})
            for field, value in values.items():
                if Decimal(actual[field] or 0) != value:
                    raise RuntimeError('FACT_AGGREGATE_MISMATCH')
                checks += 1
    state.update(status='ready', readiness=report, aggregate_checks_passed=checks,
                 dry_run_rows=preview['rows'], imported_rows=imported['rows'],
                 maintenance_held=True, database_imported=True)
    save()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Diagnostics stay in the server-private log; only fixed failure code is emitted.
        import traceback
        traceback.print_exc(file=open('/artifacts/db-stage-error.log', 'w'))
        print('SHARED_DEMO_OFFLINE_STAGE_FAILED', file=sys.stderr)
        sys.exit(1)
