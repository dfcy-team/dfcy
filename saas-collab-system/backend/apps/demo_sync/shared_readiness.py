"""Read-only acceptance checks before exposing a shared imported Demo."""
import hashlib
import importlib
import json
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.migrations.executor import MigrationExecutor

from .importer import MODEL_MAP
from .service import verified_bundle_files


class SharedReadinessError(Exception):
    pass


def shared_profile_guarded():
    return (
        getattr(settings, 'DEMO_SHARED_SNAPSHOT_INSTANCE', False)
        and getattr(settings, 'DEMO_SHARED_ADMIN_ONLY', False)
        and 'apps.demo_sync.shared_middleware.SharedDemoGateMiddleware' in settings.MIDDLEWARE
        and not any(getattr(settings, name, False) for name in (
            'LIVE_PLATFORM_SECURITY_APPROVED', 'LIVE_READONLY_SYNC_ENABLED',
            'DEMO_DATA_SYNC_ENABLED', 'DEMO_DATA_SYNC_WORKER_ENABLED',
            'DEMO_DATA_SYNC_IMPORT_ENABLED', 'DEMO_DATA_SYNC_SERVICE_INSTANCE',
            'DEMO_LOCAL_UPDATE_ENABLED'))
        and getattr(settings, 'PLATFORM_NETWORK_MODE', '') == 'mock'
        and getattr(settings, 'LIVE_CUSTODY_BACKEND', '') == 'refuse'
        and not getattr(settings, 'CELERY_BEAT_SCHEDULE', {})
        and getattr(settings, 'CELERY_BROKER_URL', '') == 'memory://'
    )


def inspect_shared_snapshot(bundle, tenant_id, expected_digest, admin_ids):
    if not shared_profile_guarded():
        raise SharedReadinessError('SHARED_PROFILE_REQUIRED')
    if set(admin_ids) != set(getattr(settings, 'DEMO_SHARED_ADMIN_IDS', ())):
        raise SharedReadinessError('ADMIN_ALLOWLIST_MISMATCH')
    if connection.vendor != 'mysql':
        raise SharedReadinessError('SHARED_MYSQL_REQUIRED')
    with connection.cursor() as cursor:
        cursor.execute('SELECT DATABASE()')
        actual = cursor.fetchone()[0]
    if not isinstance(actual, str) or not actual.startswith('saas_collab_demo_'):
        raise SharedReadinessError('SHARED_DATABASE_NOT_ISOLATED')
    marker = Path(settings.DEMO_SHARED_MAINTENANCE_FILE)
    if not marker.is_file() or any(p.is_symlink() for p in (marker, *marker.parents)):
        raise SharedReadinessError('MAINTENANCE_REQUIRED_FOR_ACCEPTANCE')
    bundle = Path(bundle)
    if not bundle.is_absolute() or any(p.is_symlink() for p in (bundle, *bundle.parents)):
        raise SharedReadinessError('BUNDLE_DIRECTORY_REJECTED')
    files = verified_bundle_files(bundle)
    raw = (bundle / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise SharedReadinessError('REVIEWED_MANIFEST_MISMATCH')
    manifest = json.loads(raw)
    if manifest.get('scope_key', '').split(':', 1)[0] != str(tenant_id):
        raise SharedReadinessError('SNAPSHOT_TENANT_MISMATCH')
    source_counts = {v['resource']: v['count'] for v in manifest['files']}
    if set(source_counts) != set(MODEL_MAP):
        raise SharedReadinessError('SNAPSHOT_RESOURCE_SET_INVALID')
    # All following operations are aggregates/SELECTs. No migration/import is run.
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise SharedReadinessError('MIGRATIONS_PENDING')
    from apps.accounts.models import CustomUser
    from apps.commerce.models import SalesOrder, SalesOrderItem, InventorySnapshot
    from apps.integrations.models import InternalAPIClient, PlatformIntegrationConfig, SyncJob
    from .models import ImportedSnapshotReceipt, SnapshotIdentity

    target_counts = {}
    mapping_violations = 0
    for resource, (module, name) in MODEL_MAP.items():
        model = getattr(importlib.import_module(module), name)
        qs = model.objects.all()
        # A fresh work database must contain exactly this package, across all tenants.
        target_counts[resource] = qs.count()
        mapping_violations += identity_mapping_violations(model, resource, tenant_id)
    identities = dict(SnapshotIdentity.objects.filter(tenant_id=tenant_id).values('resource')
                      .annotate(n=Count('pk')).values_list('resource', 'n'))
    receipt = ImportedSnapshotReceipt.objects.filter(tenant_id=tenant_id).values_list('manifest_sha256', flat=True).first()
    constraints = 0
    for model, fields in (
        (SalesOrder, ('platform', 'store', 'authorization', 'source_run')),
        (InventorySnapshot, ('warehouse', 'internal_sku', 'source_run')),
    ):
        for field in fields:
            constraints += model.objects.filter(tenant_id=tenant_id, **{field + '__isnull': False}).exclude(
                **{field + '__tenant_id': F('tenant_id')}).count()
    # Order items inherit tenancy through their order; they have no tenant column.
    for field in ('internal_spu', 'internal_sku'):
        constraints += SalesOrderItem.objects.filter(
            sales_order__tenant_id=tenant_id, **{field + '__isnull': False}
        ).exclude(**{field + '__tenant_id': F('sales_order__tenant_id')}).count()
    unsafe_sources = PlatformIntegrationConfig.objects.filter(
        Q(network_enabled=True) | Q(sync_read_enabled=True) | Q(sync_write_enabled=True)
        | ~Q(credential_id='') | ~Q(credential_mask={})).count()
    state = {
        'source_counts': source_counts, 'target_counts': target_counts,
        'identity_counts': {r: identities.get(r, 0) for r in MODEL_MAP},
        'receipt_matches': receipt == expected_digest,
        'receipt_count': ImportedSnapshotReceipt.objects.count(),
        'constraint_violations': constraints + mapping_violations,
        'unsafe_sources': unsafe_sources, 'enabled_jobs': SyncJob.objects.filter(is_enabled=True).count(),
        'machine_clients': InternalAPIClient.objects.count(),
        'admins_present': CustomUser.objects.filter(pk__in=admin_ids, tenant_id=tenant_id,
                                                    user_type='internal', is_active=True, is_superuser=True).count(),
        'expected_admin_count': len(admin_ids),
        'unexpected_active_users': CustomUser.objects.filter(is_active=True).exclude(pk__in=admin_ids).count(),
        'verified_files': len(files),
    }
    return evaluate_shared_state(state)


def identity_mapping_violations(model, resource, tenant_id):
    """Aggregate dangling, duplicate and cross-tenant importer target pointers."""
    from .models import SnapshotIdentity

    mappings = SnapshotIdentity.objects.filter(tenant_id=tenant_id, resource=resource)
    target = model.objects.filter(pk=OuterRef('target_id'))
    tenant_lookup = 'sales_order__tenant_id' if resource == 'sales_order_items' else 'tenant_id'
    target = target.filter(**{tenant_lookup: tenant_id})
    missing_or_foreign = mappings.annotate(target_valid=Exists(target)).filter(target_valid=False).count()
    duplicates = mappings.values('target_id').annotate(n=Count('pk')).filter(n__gt=1).count()
    return missing_or_foreign + duplicates


def evaluate_shared_state(state):
    errors = []
    if not state['receipt_matches'] or state['receipt_count'] != 1:
        errors.append('IMPORT_RECEIPT_MISMATCH')
    if state['source_counts'] != state['target_counts'] or state['target_counts'] != state['identity_counts']:
        errors.append('ROW_ACCOUNTING_MISMATCH')
    if state['constraint_violations']:
        errors.append('TENANT_RELATION_VIOLATIONS')
    if state['unsafe_sources'] or state['enabled_jobs'] or state['machine_clients']:
        errors.append('LIVE_LOCAL_SOURCE_OR_JOB_PRESENT')
    if state['admins_present'] != state['expected_admin_count'] or state['unexpected_active_users']:
        errors.append('INITIAL_ADMIN_AUDIENCE_MISMATCH')
    fact_resources = ('sales_orders', 'sales_order_items', 'inventory_snapshots')
    source_rows = sum(state['source_counts'].get(r, 0) for r in fact_resources)
    if source_rows == 0:
        errors.append('EMPTY_FACT_SNAPSHOT')
    return {
        'status': 'SHARED_SNAPSHOT_REVIEW_READY' if not errors else 'SHARED_SNAPSHOT_REJECTED',
        'source_rows': source_rows,
        'target_rows': sum(state['target_counts'].get(r, 0) for r in fact_resources),
        'schema_diff_count': None,  # migration check is not a cross-database schema comparison
        'constraint_violations': state['constraint_violations'], 'mismatched_chunks': [],
        'sample_artifact': None, 'errors': errors,
        'recommended_action': 'Review admin-only preview and controlled cutover; no switch performed.' if not errors else 'Keep maintenance enabled and investigate failed gates.',
        'row_counts': state['target_counts'], 'audience': 'approved_internal_superusers_only',
        'switch_performed': False,
    }
