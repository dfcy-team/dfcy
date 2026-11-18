import pytest
from rest_framework.test import APIRequestFactory, force_authenticate
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from apps.influencers.models import OutreachTask
from apps.influencers.views import OutreachTaskCollectionView
from apps.influencers.services import transition_outreach_task
from apps.influencers.tests.test_import_compatibility import sample_records
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.accounts.models import CustomUser

pytestmark = pytest.mark.django_db


def test_priority_tasks_keep_tenant_and_store_scope(sample_records):
    # Isolate this scope from any seeded default BD role in a migrated CI DB.
    user = CustomUser.objects.create_user(tenant=sample_records['tenant'], username='priority-only-reader', user_type='internal')
    role = Role.objects.create(tenant=user.tenant, name='Priority reader', code='priority-reader')
    permission, _ = Permission.objects.get_or_create(code='influencers.outreach.view')
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    warehouse = WarehouseMaster.objects.create(tenant=user.tenant, code='priority-wh', name='PH', country_code='PH',
                                              warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
                             config={'store_ids': [sample_records['store'].pk], 'warehouse_ids': [warehouse.pk]})
    original = OutreachTask.objects.create(tenant=user.tenant, task_no='visible-priority',
                                          owner=user, dispatcher=user, store=sample_records['store'], priority='urgent')
    other_tenant = sample_records['other_user'].tenant
    platform = PlatformMaster.objects.create(tenant=other_tenant, code='priority-platform', name='Other', platform_type=PlatformMaster.PlatformType.TIKTOK)
    foreign_store = StoreMaster.objects.create(tenant=other_tenant, platform=platform, code='priority-store',
                                              name='Other', country_code='PH', currency='PHP')
    for number, tenant, store, status in [
        ('hidden-store', user.tenant, sample_records['second_store'], 'pending'),
        ('completed', user.tenant, sample_records['store'], 'completed'),
        ('foreign', other_tenant, foreign_store, 'pending'),
    ]:
        actor = user if tenant == user.tenant else sample_records['other_user']
        task = OutreachTask.objects.create(tenant=tenant, task_no=number, store=store, priority='urgent',
                                          owner=actor, dispatcher=actor)
        if status == 'completed':
            task = transition_outreach_task(user=actor, task=task, status='in_progress', expected_version=task.version)
            transition_outreach_task(user=actor, task=task, status='completed', expected_version=task.version)
    request = APIRequestFactory().get('/tasks/', {'priority_only': 'true'})
    force_authenticate(request, user)
    response = OutreachTaskCollectionView.as_view()(request)
    assert response.status_code == 200, response.data
    groups = response.data['data']['priority_tasks']
    assert [row['id'] for row in groups['urgent']] == [original.pk]
    assert groups['high'] == []


@pytest.mark.django_db(transaction=True)
def test_release_guard_rejects_missing_live_migration():
    recorder = MigrationRecorder(connection)
    recorder.record_applied('influencers', '9999_unmerged_hotfix')
    with pytest.raises(CommandError, match='9999_unmerged_hotfix'):
        call_command('check_influencer_hotfix_compatibility')
    assert ('influencers', '9999_unmerged_hotfix') in recorder.applied_migrations()
