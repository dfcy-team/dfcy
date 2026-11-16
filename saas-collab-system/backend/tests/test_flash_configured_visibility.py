import pytest
from django.utils import timezone
from apps.flash_sales.models import StoreConfig
from apps.masterdata.models import StoreMaster
from apps.permissions.models import Role
from tests.test_flash_sales import shop
from tests.test_flash_access_boundaries import scoped_client, make_activity, BASE

pytestmark = pytest.mark.django_db


def test_activity_list_intersects_visible_and_configured_stores(shop):
    admin, store, client = shop
    StoreConfig.objects.create(tenant=admin.tenant, store=store, stock=1)
    for code, configured, deleted in [('UNCONFIGURED', False, False), ('DELETED', True, True), ('HIDDEN', True, False)]:
        other = StoreMaster.objects.create(tenant=admin.tenant, platform=store.platform, code=code, name=code)
        if configured:
            StoreConfig.objects.create(tenant=admin.tenant, store=other, stock=1, deleted_at=timezone.now() if deleted else None)
        make_activity(admin, other, code)
    make_activity(admin, store, 'VISIBLE')
    unconfigured = StoreMaster.objects.get(code='UNCONFIGURED', tenant=admin.tenant)
    assert client.get(BASE+'workspace/', {'store_id':unconfigured.pk}).data['data']['activity_total'] == 0
    _, client = scoped_client(shop)
    data = client.get(BASE+'workspace/').data['data']
    assert [a['platform_id'] for a in data['activities']] == ['VISIBLE']
    assert data['activity_counts']['all'] == 1


def test_non_admin_cannot_change_notifications_even_with_permissions(shop):
    admin, store, _ = shop
    config = StoreConfig.objects.create(tenant=admin.tenant, store=store, stock=1)
    _, client = scoped_client(shop, ('view','configure','notifications'))
    data = client.get(BASE+'workspace/').data['data']
    assert data['capabilities']['notification_settings'] is False
    payload = {'stores':[{'store_id':store.pk,'version':config.version,'notification_mode':'disabled','recipient_ids':[]}]}
    assert client.put(BASE+'notifications/', payload, format='json').status_code == 403
    assert client.put(BASE+f'configs/{store.pk}/', {'version':config.version,'notification_mode':'disabled'}, format='json').status_code == 403
    config.refresh_from_db(); assert config.notification_mode == 'owner'
    # Normal stock edits remain available.
    assert client.put(BASE+f'configs/{store.pk}/', {'version':config.version,'stock':2}, format='json').status_code == 200


def test_tenant_administrator_can_manage_store_notifications(shop):
    admin, store, _ = shop
    config = StoreConfig.objects.create(tenant=admin.tenant, store=store, stock=1)
    _, client = scoped_client(shop, ('view','configure','notifications'))
    role = Role.objects.get(tenant=admin.tenant,code='scoped');role.code='administrator';role.save()
    assert client.get(BASE+'workspace/').data['data']['capabilities']['notification_settings'] is True
    response = client.put(BASE+'notifications/', {'stores':[{'store_id':store.pk,'version':config.version,'notification_mode':'disabled','recipient_ids':[]}]},format='json')
    assert response.status_code == 200
