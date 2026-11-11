from copy import deepcopy
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command, CommandError

from apps.demo_sync.shared_readiness import evaluate_shared_state


def state():
    counts = {'sales_orders': 2, 'sales_order_items': 1, 'inventory_snapshots': 1}
    return {'source_counts': counts, 'target_counts': dict(counts), 'identity_counts': dict(counts),
            'receipt_matches': True, 'receipt_count': 1, 'constraint_violations': 0,
            'unsafe_sources': 0, 'enabled_jobs': 0, 'machine_clients': 0,
            'admins_present': 1, 'expected_admin_count': 1, 'unexpected_active_users': 0}


def test_ready_is_review_only_never_switches():
    result = evaluate_shared_state(state())
    assert result['status'] == 'SHARED_SNAPSHOT_REVIEW_READY'
    assert result['source_rows'] == result['target_rows'] == 4
    assert result['switch_performed'] is False
    assert result['schema_diff_count'] is None


@pytest.mark.parametrize('field,value,code', [
    ('receipt_matches', False, 'IMPORT_RECEIPT_MISMATCH'),
    ('enabled_jobs', 1, 'LIVE_LOCAL_SOURCE_OR_JOB_PRESENT'),
    ('unsafe_sources', 1, 'LIVE_LOCAL_SOURCE_OR_JOB_PRESENT'),
    ('machine_clients', 1, 'LIVE_LOCAL_SOURCE_OR_JOB_PRESENT'),
    ('constraint_violations', 1, 'TENANT_RELATION_VIOLATIONS'),
    ('admins_present', 0, 'INITIAL_ADMIN_AUDIENCE_MISMATCH'),
    ('unexpected_active_users', 39, 'INITIAL_ADMIN_AUDIENCE_MISMATCH'),
])
def test_failed_gates_reject(field, value, code):
    data = deepcopy(state())
    data[field] = value
    assert code in evaluate_shared_state(data)['errors']


def test_untracked_local_business_rows_reject():
    data = state()
    data['target_counts']['sales_orders'] += 1
    assert 'ROW_ACCOUNTING_MISMATCH' in evaluate_shared_state(data)['errors']


def test_default_profile_rejects_before_any_database_query():
    with patch('apps.demo_sync.shared_readiness.connection') as db:
        with pytest.raises(CommandError, match='SHARED_PROFILE_REQUIRED'):
            call_command('check_shared_demo_snapshot', bundle='/private/bundle', tenant_id=1,
                         manifest_sha256='a' * 64, admin_id=[1], stdout=StringIO())
    db.cursor.assert_not_called()


@pytest.mark.django_db
def test_mapping_rejects_missing_duplicate_and_foreign_targets():
    from apps.demo_sync.models import SnapshotIdentity
    from apps.demo_sync.shared_readiness import identity_mapping_violations
    from apps.products.models import ProductCategory
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.create(name='Shared synthetic', code='shared-mapping-test')
    other = Tenant.objects.create(name='Other synthetic', code='shared-mapping-other')
    target = ProductCategory.objects.create(tenant=tenant, code='1', level=1, name='Own')
    foreign = ProductCategory.objects.create(tenant=other, code='2', level=1, name='Other')
    mapping = SnapshotIdentity.objects.create(tenant=tenant, resource='product_categories',
                                               source_id='one', target_id=target.pk)
    assert identity_mapping_violations(ProductCategory, 'product_categories', tenant.pk) == 0
    mapping.target_id = 999999999
    mapping.save(update_fields=['target_id'])
    assert identity_mapping_violations(ProductCategory, 'product_categories', tenant.pk) == 1
    mapping.target_id = foreign.pk
    mapping.save(update_fields=['target_id'])
    assert identity_mapping_violations(ProductCategory, 'product_categories', tenant.pk) == 1
    mapping.target_id = target.pk
    mapping.save(update_fields=['target_id'])
    SnapshotIdentity.objects.create(tenant=tenant, resource='product_categories',
                                    source_id='two', target_id=target.pk)
    assert identity_mapping_violations(ProductCategory, 'product_categories', tenant.pk) == 1
