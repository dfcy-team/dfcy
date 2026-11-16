from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.flash_sales.models import Activity, Batch, StoreTask
from apps.masterdata.models import StoreMaster
from apps.permissions.models import Permission, Role, RoleResourcePolicy, UserRole
from tests.test_flash_sales import shop, _admin

pytestmark = pytest.mark.django_db
BASE = '/api/internal/marketing/flash-sales/'


def scoped_client(shop, actions=('view',), ids=None):
    admin, store, client = shop
    user = CustomUser.objects.create_user(username='scoped', tenant=admin.tenant, user_type='internal')
    role = Role.objects.create(tenant=admin.tenant, code='scoped', name='Scoped')
    for action in actions:
        code = 'marketing.flash_sales.' + action
        permission, _ = Permission.objects.get_or_create(code=code, defaults={
            'name': action, 'module':'marketing', 'action':action, 'permission_type':'action'})
        role.permissions.add(permission)
        if ids != []:
            RoleResourcePolicy.objects.create(tenant=admin.tenant, role=role, resource_code='marketing.flash_sales',
                permission_code=code, scope_type='custom', config={'store_ids': ids if ids is not None else [store.pk]})
    UserRole.objects.create(tenant=admin.tenant, role=role, user=user)
    client.force_authenticate(user)
    return user, client


def make_activity(user, store, key):
    return Activity.objects.create(tenant=user.tenant, store=store, platform_id=key, slot_id=key, platform_status=1,
        starts_at=timezone.now(), ends_at=timezone.now()+timedelta(hours=1), synced_at=timezone.now())


def test_workspace_and_batch_filter_same_tenant_hidden_store(shop):
    admin, store, _ = shop
    hidden = StoreMaster.objects.create(tenant=admin.tenant, platform=store.platform, code='HIDDEN', name='Hidden')
    batch = Batch.objects.create(tenant=admin.tenant, actor=admin, source='manual', request_id='mixed', payload_hash='x')
    for s in (store, hidden):
        StoreTask.objects.create(tenant=admin.tenant, store=s, batch=batch)
        make_activity(admin,s,str(s.pk))
    _, client = scoped_client(shop, ('view','execute'))
    data = client.get(BASE+'workspace/').data['data']
    assert [s['id'] for s in data['stores']] == [store.pk]
    assert data['activity_total'] == 1
    assert [t['store_id'] for t in data['batches'][0]['tasks']] == [store.pk]
    detail = client.get(BASE+f'batches/{batch.pk}/').data['data']
    assert [t['store_id'] for t in detail['tasks']] == [store.pk]
    assert client.post(BASE+f'batches/{batch.pk}/', {'action':'stop'}, format='json').status_code == 403
    batch.refresh_from_db()
    assert not batch.stop_requested
    hidden_activity = Activity.objects.get(store=hidden)
    assert client.get(BASE+f'activities/{hidden_activity.pk}/').status_code == 404
    assert client.post(BASE+'batches/', {'request_id':'hidden','store_ids':[hidden.pk]}, format='json').status_code == 403


@pytest.mark.parametrize('action', ['run','sync','copy','toggle','delete'])
def test_view_only_cannot_submit_any_operation(shop, action):
    _, store, _ = shop
    _, client = scoped_client(shop)
    with patch('apps.flash_sales.provider.ShopeeAdapter.call') as call:
        response = client.post(BASE+'batches/', {'request_id':'readonly','store_ids':[store.pk],
            'operation':action, 'confirmed':True}, format='json')
    assert response.status_code == 403
    assert not Batch.objects.exists()
    call.assert_not_called()


def test_foreign_tenant_admin_cannot_read_or_mutate_resources(shop):
    admin, store, _ = shop
    activity = make_activity(admin,store,'foreign')
    batch = Batch.objects.create(tenant=admin.tenant, actor=admin, source='manual', request_id='foreign', payload_hash='x')
    StoreTask.objects.create(tenant=admin.tenant, store=store, batch=batch)
    _, _, client = _admin('foreign-boundary')
    assert client.get(BASE+f'activities/{activity.pk}/').status_code == 404
    assert client.get(BASE+f'activities/{activity.pk}/source/').status_code == 404
    assert client.get(BASE+f'batches/{batch.pk}/').status_code == 404
    assert client.post(BASE+f'batches/{batch.pk}/', {'action':'stop'}, format='json').status_code == 404
    assert client.post(BASE+'previews/', {'store_id':store.pk}, format='json').status_code == 403
    assert client.put(BASE+f'configs/{store.pk}/', {'stock':1}, format='json').status_code == 403
    assert client.get(BASE+'workspace/', {'history_store_id':store.pk}).data['data']['batch_total'] == 0


def test_empty_scope_does_not_expand_to_all_stores(shop):
    _, store, _ = shop
    _, client = scoped_client(shop, ('view','execute'), [])
    data = client.get(BASE+'workspace/').data['data']
    assert data['stores'] == [] and data['activities'] == [] and data['batches'] == []
    assert client.post(BASE+'batches/', {'request_id':'empty','store_ids':[store.pk]}, format='json').status_code == 403


def test_anonymous_and_inactive_users_cannot_view(shop):
    user, _, client = shop
    client.force_authenticate(None)
    assert client.get(BASE+'workspace/').status_code in {401,403}
    user.is_active = False
    user.save(update_fields=['is_active'])
    client.force_authenticate(user)
    assert client.get(BASE+'workspace/').status_code == 403
