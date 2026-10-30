"""Authorization-center read contracts against isolated nonempty tenant fixtures."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.integrations.models import WarehouseAuthorization, PlatformIntegrationConfig, SyncJob
from apps.masterdata.models import WarehouseMaster, PlatformMaster
from apps.permissions.models import Role, UserRole
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from tests.test_connection_capability_matrix import make_authorization, grant

pytestmark = pytest.mark.django_db

@pytest.fixture
def subjects():
    records = []
    for code in ('center-tenant-a', 'center-tenant-b'):
        tenant, owner, store = make_authorization(code)
        provider = PlatformMaster.objects.create(tenant=tenant, code='myjf', name='Jifeng', platform_type='warehouse_third_party')
        warehouse = WarehouseMaster.objects.create(tenant=tenant, code='test-warehouse', name='Isolated warehouse', country_code='PH', warehouse_type='third_party', service_platform=provider)
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform='jifeng_wms', account_alias='test-warehouse', created_by=owner)
        binding = WarehouseAuthorization.objects.create(tenant=tenant, integration_config=config, warehouse=warehouse, provider='jifeng_wms', external_warehouse_code=code, external_warehouse_region='PH', credential_id='synthetic-reference', status='active', created_by=owner, updated_by=owner)
        store_job = SyncJob.objects.create(tenant=tenant, integration_config=store.integration_config, store_authorization=store, resource_type='sales_order')
        warehouse_job = SyncJob.objects.create(tenant=tenant, integration_config=config, warehouse_authorization=binding, resource_type='inventory_snapshot')
        records.append((tenant, store, binding, store_job, warehouse_job))
    return records

def viewer(tenant, role_code):
    user = CustomUser.objects.create_user(username=f'reader-{role_code}', tenant=tenant, user_type='internal')
    role = Role.objects.get_or_create(tenant=tenant, code=role_code, defaults={'name': role_code})[0]
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    client = APIClient(); client.force_authenticate(user)
    return client, user

@pytest.mark.parametrize('role_code', ['administrator', 'admin', 'tech_admin', 'integration_admin'])
def test_api_admin_can_read_both_authorization_types_only_in_current_tenant(subjects, role_code):
    own, other = subjects
    client, user = viewer(own[0], role_code)
    for kind, index, job_index in [('store',1,3),('warehouse',2,4)]:
        root = f'/api/internal/integrations/{kind}-authorizations/'
        response = client.get(root)
        assert response.status_code == 200, response.data
        assert [row['id'] for row in response.data['data']['results']] == [own[index].id]
        assert client.get(f'{root}{own[index].id}/').status_code == 200
        assert client.get(f'{root}{other[index].id}/').status_code == 404
        subject_id = getattr(own[index], f'{kind}_id')
        candidates = client.get('/api/internal/integrations/subject-candidates/', {'type':kind,'page_size':1})
        assert candidates.status_code == 200, candidates.data
        assert candidates.data['data']['count'] == 1
        if kind == 'warehouse':
            assert candidates.data['data']['results'][0]['api_access_available'] is True
        assert [row['id'] for row in candidates.data['data']['results']] == [subject_id]
        summary = client.get('/api/internal/integrations/subject-api-access/', {'subject_type':kind,'subject_id':subject_id})
        assert summary.status_code == 200, summary.data

        response = client.get('/api/internal/integrations/workspace/', {'mode':'sync-jobs','subject_key':f'{kind}:{subject_id}'})
        assert response.status_code == 200, response.data
        assert [row['id'] for row in response.data['data']['results']] == [own[job_index].id]
        foreign_id = getattr(other[index], f'{kind}_id')
        assert client.get('/api/internal/integrations/subject-api-access/', {'subject_type':kind,'subject_id':foreign_id}).status_code == 404
        foreign = client.get('/api/internal/integrations/workspace/', {'mode':'sync-jobs','subject_key':f'{kind}:{foreign_id}'})
        assert foreign.status_code == 200 and foreign.data['data']['results'] == []
    for path in ('feishu/connection/', 'internal-api-clients/'):
        assert client.get('/api/internal/integrations/'+path).status_code == 200
    assert not check_user_permission(user, 'config.system.manage')
    assert not check_user_permission(user, 'finance.view')
    assert client.get('/api/internal/integrations/subject-candidates/', {'type':'invalid'}).status_code == 400
    assert client.get('/api/internal/integrations/subject-candidates/', {'type':'store', 'page_size':101}).status_code == 400


def test_nonadmin_grants_do_not_open_api_module(subjects):
    own, _ = subjects
    user = CustomUser.objects.create_user(username='business-viewer', tenant=own[0], user_type='internal')
    grant(user, 'integrations.view', 'integrations.store.view', 'integrations.warehouse.view', 'feishu.view', 'integrations.internal_api_client.view')
    client = APIClient(); client.force_authenticate(user)
    for path in ('store-authorizations/', 'warehouse-authorizations/', 'feishu/connection/', 'internal-api-clients/'):
        assert client.get('/api/internal/integrations/'+path).status_code == 403
    assert get_permission_data_scopes(user, 'integrations.store.view') == []
    assert not check_user_permission(user, 'finance.view')
    assert not check_user_permission(user, 'config.system.manage')
    assert client.get('/api/internal/integrations/subject-candidates/', {'type':'store'}).status_code == 403


def test_revoked_admin_role_has_no_access(subjects):
    client, user = viewer(subjects[0][0], 'tech_admin')
    Role.objects.filter(tenant=user.tenant, code='tech_admin').update(status='disabled')
    assert client.get('/api/internal/integrations/store-authorizations/').status_code == 403


@pytest.mark.parametrize('invalid_state', [
    'expired_binding', 'disabled_binding', 'disabled_role', 'inactive_internal', 'external_superuser',
])
def test_inactive_or_invalid_admin_identities_are_denied(subjects, invalid_state):
    client, user = viewer(subjects[0][0], f'api-admin-{invalid_state}')
    binding = UserRole.objects.get(user=user, tenant=user.tenant)
    if invalid_state == 'expired_binding':
        binding.valid_until = timezone.now() - timedelta(seconds=1)
        binding.save(update_fields=['valid_until'])
    elif invalid_state == 'disabled_binding':
        binding.status = Role.Status.INACTIVE
        binding.save(update_fields=['status'])
    elif invalid_state == 'disabled_role':
        Role.objects.filter(pk=binding.role_id).update(status=Role.Status.INACTIVE)
    elif invalid_state == 'inactive_internal':
        user.is_active = False
        user.save(update_fields=['is_active'])
    elif invalid_state == 'external_superuser':
        user.user_type = CustomUser.UserType.EXTERNAL
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=['user_type', 'is_superuser', 'is_staff'])

    assert not check_user_permission(user, 'integrations.view')
    assert not check_user_permission(user, 'finance.view')
    assert not check_user_permission(user, 'config.system.manage')
    assert client.get('/api/internal/integrations/store-authorizations/').status_code == 403
