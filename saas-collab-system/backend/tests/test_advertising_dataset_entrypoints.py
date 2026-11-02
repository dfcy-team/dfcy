import pytest
from rest_framework.test import APIClient
from apps.permissions.models import Permission,Role,UserRole
from apps.integrations.models import ShopeeAdvertisingRecord
from apps.reports.models import SavedReportView,SavedReportViewRevision
from tests.test_sales_realtime_board import _fixture,DAY

pytestmark=pytest.mark.django_db
BASE='/api/report/'

def ad_config():
    return {'dataset':'advertising','dimensions':['store_id','currency'],'metrics':['record_count'],'filters':{'date_from':DAY,'date_to':DAY},'chart':'table'}

def finance_config():
    return {'dataset':'finance','dimensions':['currency'],'metrics':['transaction_count'],'filters':{}}

@pytest.fixture
def assigned_report_reader():
    user,tenant,platform,store,run,_=_fixture('ad-entrypoints')
    UserRole.objects.filter(user=user).delete()
    role=Role.objects.create(tenant=tenant,code='ad-action-only',name='Ad reader')
    for code in ['reports.view','analytics.view','finance.view']:
        permission,_=Permission.objects.get_or_create(code=code,defaults={'name':code,'module':code.split('.')[0],'action':'view'})
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant,user=user,role=role)
    store.operator=user;store.save(update_fields=['operator'])
    ShopeeAdvertisingRecord.objects.create(tenant=tenant,store=store,source_run=run,kind='shop_daily',record_key='entry-ad',report_date=DAY,currency='PHP',report_timezone='Asia/Manila',dimensions={},data={'expense':'1'})
    client=APIClient();client.force_authenticate(user)
    return client,user,tenant,store

def test_ad_catalog_query_and_options_work_without_legacy_report_scope(assigned_report_reader):
    client,user,tenant,store=assigned_report_reader
    catalog=client.get(BASE+'datasets/');assert catalog.status_code==200,catalog.data
    assert {row['id'] for row in catalog.data['data']['datasets']}=={'advertising'}
    result=client.post(BASE+'query/',ad_config(),format='json');assert result.status_code==200,result.data
    assert {row['store_id'] for row in result.data['data']['rows']}=={store.pk}
    options=client.post(BASE+'filter-options/',{'dataset':'advertising'},format='json')
    assert options.status_code==200,options.data
    assert {row['value'] for row in options.data['data']['options']}=={str(store.pk)}
    assert client.post(BASE+'query/',finance_config(),format='json').status_code==403
    assert client.post(BASE+'filter-options/',{'dataset':'finance'},format='json').status_code==403

def test_ad_dashboard_can_be_saved_updated_and_archived(assigned_report_reader):
    client,user,tenant,store=assigned_report_reader
    dashboard={'kind':'dashboard','version':1,'module':'经营分析','filters':{},'widgets':[{'id':'ad','title':'Ads','type':'table','width':12,'height':240,'config':ad_config()}]}
    created=client.post(BASE+'views/',{'name':'Ads','config':dashboard},format='json')
    assert created.status_code==201,created.data
    pk=created.data['data']['id']
    listed=client.get(BASE+'views/');assert listed.status_code==200
    assert {row['id'] for row in listed.data['data']}=={pk}
    updated=client.put(BASE+f'views/{pk}/',{'name':'Ads renamed','config':dashboard,'expected_version':1},format='json')
    assert updated.status_code==200,updated.data
    assert client.delete(BASE+f'views/{pk}/').status_code==200
    assert SavedReportView.objects.get(pk=pk).is_archived

@pytest.mark.parametrize('method',['put','delete'])
def test_ad_fallback_cannot_modify_existing_non_ad_view(assigned_report_reader,method):
    client,user,tenant,store=assigned_report_reader
    view=SavedReportView.objects.create(tenant=tenant,owner=user,name='Finance',config=finance_config())
    before=SavedReportView.objects.values().get(pk=view.pk);revisions=SavedReportViewRevision.objects.count()
    response=getattr(client,method)(BASE+f'views/{view.pk}/',{'name':'Ads','config':ad_config(),'expected_version':1},format='json')
    assert response.status_code==403,response.data
    assert SavedReportView.objects.values().get(pk=view.pk)==before
    assert SavedReportViewRevision.objects.count()==revisions

def test_ad_fallback_does_not_expose_non_ad_views_or_history(assigned_report_reader):
    client,user,tenant,store=assigned_report_reader
    non_ad=SavedReportView.objects.create(tenant=tenant,owner=user,name='Finance',config=finance_config())
    ad=SavedReportView.objects.create(tenant=tenant,owner=user,name='Ads',config=ad_config(),version=2)
    SavedReportViewRevision.objects.create(view=ad,version=1,config=finance_config(),name='Old finance',action='create',actor=user)
    SavedReportViewRevision.objects.create(view=ad,version=2,config=ad_config(),name='Ads',action='update',actor=user)
    response=client.get(BASE+'views/');assert response.status_code==200
    assert {row['id'] for row in response.data['data']}=={ad.pk}
    assert client.get(BASE+f'views/{ad.pk}/history/').status_code==403
