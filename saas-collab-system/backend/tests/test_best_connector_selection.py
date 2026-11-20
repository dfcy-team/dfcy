from types import SimpleNamespace
import pytest
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.masterdata.models import PlatformMaster
from apps.masterdata.serializers import PlatformMasterSerializer
from apps.integrations.platform_schema_service import integration_platform_key, platform_api_type_options
from apps.integrations.workspace_service import _reference_options

@pytest.mark.parametrize('code,name', [('BEST','百世'),('RENAMED','已改名的服务商')])
def test_explicit_best_connector_does_not_depend_on_display_name(code,name):
    assert integration_platform_key(platform_type='warehouse_third_party',warehouse_connector_state='selected',warehouse_connector_key='best_ecapi',code=code,name=name)=='best_ecapi'
    assert platform_api_type_options('best_ecapi')==[{'value':'inventory','label':'库存 API'}]

@pytest.mark.parametrize('state', [None,'pending','none'])
@pytest.mark.parametrize('code,name', [('BEST','百世'),('jifeng','极风')])
def test_names_do_not_implicitly_enable_unconfirmed_connectors(state,code,name):
    assert integration_platform_key(platform_type='warehouse_third_party',warehouse_connector_state=state,warehouse_connector_key='best_ecapi',code=code,name=name)==''

@pytest.mark.django_db
def test_all_tenants_can_select_confirmed_best_but_never_see_other_tenant_rows(settings):
    settings.BEST_ECAPI_ENABLED=False
    identities=[]
    for number in [1,2]:
        tenant=Tenant.objects.create(code=f'best-selector-{number}',name=f'Tenant {number}')
        user=CustomUser.objects.create_user(username=f'best-selector-{number}',tenant=tenant,user_type='internal',is_superuser=True)
        best=PlatformMaster.objects.create(tenant=tenant,code='BEST',name='百世',platform_type='warehouse_third_party',warehouse_connector_state='selected',warehouse_connector_key='best_ecapi')
        PlatformMaster.objects.create(tenant=tenant,code='pending',name='待确认',platform_type='warehouse_third_party',warehouse_connector_state='pending')
        PlatformMaster.objects.create(tenant=tenant,code='none',name='暂不接入',platform_type='warehouse_third_party',warehouse_connector_state='none')
        jf=PlatformMaster.objects.create(tenant=tenant,code='jifeng',name='极风',platform_type='warehouse_third_party',warehouse_connector_state='selected',warehouse_connector_key='jifeng_wms')
        sp=PlatformMaster.objects.create(tenant=tenant,code='SP',name='Shopee',platform_type='shopee')
        identities.append((user,best,jf,sp))
    for user,best,jf,sp in identities:
        options=_reference_options(user)['platforms']
        assert {row['id'] for row in options}=={best.pk,jf.pk,sp.pk}
        result=next(row for row in options if row['id']==best.pk)
        assert result['value']=='best_ecapi' and result['enabled']
        assert result['api_types']==[{'value':'inventory','label':'库存 API'}]
        data=PlatformMasterSerializer(best,context={'request':SimpleNamespace(user=user)}).data
        assert data['connector_key']=='best_ecapi' and data['connector_status']=='TESTING'

@pytest.mark.django_db
def test_tenant_admin_can_choose_connector_without_enabling_live_api(settings):
    from django.urls import reverse
    from rest_framework.test import APIClient
    from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization
    tenant=Tenant.objects.create(code='best-edit',name='Best edit')
    user=CustomUser.objects.create_user(username='best-edit',tenant=tenant,user_type='internal',is_superuser=True)
    platform=PlatformMaster.objects.create(tenant=tenant,code='BEST',name='百世',platform_type='warehouse_third_party',warehouse_connector_state='pending')
    client=APIClient();client.force_authenticate(user)
    url=reverse('master-data-detail',kwargs={'resource':'platforms','pk':platform.pk})
    settings.BEST_ECAPI_ENABLED=False
    body={'warehouse_connector_state':'selected','warehouse_connector_key':'best_ecapi','version':1}
    response=client.patch(url,body,format='json')
    assert response.status_code==200,response.data
    assert response.data['data']['connector_key']=='best_ecapi'
    assert response.data['data']['version']==2
    assert client.patch(url,body,format='json').status_code==409
    assert not PlatformIntegrationConfig.objects.exists() and not WarehouseAuthorization.objects.exists()
    assert not settings.BEST_ECAPI_ENABLED
    other=Tenant.objects.create(code='best-edit-other',name='Other')
    other_user=CustomUser.objects.create_user(username='best-edit-other',tenant=other,user_type='internal',is_superuser=True)
    client.force_authenticate(other_user)
    assert client.patch(url,{**body,'version':2},format='json').status_code==404
    client.force_authenticate(user)
    assert client.patch(url,{**body,'warehouse_connector_key':'unknown','version':2},format='json').status_code==400
    platform.refresh_from_db()
    assert platform.warehouse_connector_key=='best_ecapi'

@pytest.mark.django_db
def test_existing_warehouse_binding_prevents_connector_switch():
    from django.urls import reverse
    from rest_framework.test import APIClient
    from tests.test_warehouse_api_binding_closure import _fixture
    user,warehouse,config,_=_fixture()
    client=APIClient();client.force_authenticate(user)
    bound=client.post('/api/internal/integrations/warehouse-authorizations/',{'warehouse_id':warehouse.pk,'integration_config_id':config.pk},format='json')
    assert bound.status_code==201,bound.data
    platform=warehouse.service_platform
    response=client.patch(reverse('master-data-detail',kwargs={'resource':'platforms','pk':platform.pk}),
      {'warehouse_connector_state':'selected','warehouse_connector_key':'best_ecapi','version':platform.version},format='json')
    assert response.status_code==400
    platform.refresh_from_db()
    assert platform.warehouse_connector_key=='jifeng_wms'
