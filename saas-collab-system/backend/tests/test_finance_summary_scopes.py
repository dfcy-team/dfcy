"""Synthetic shared-result authorization; never touches provider APIs."""
import pytest
from unittest.mock import Mock
from apps.finance.summary_service import READ_PERMISSIONS
from apps.finance.summary_jobs import run_calculation
from apps.finance.summary_models import FinanceSummaryCalculation
from apps.finance.summary_scopes import store_ids
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope
from tests.test_finance_summary import context,URL
from tests.test_sales_management import grant,user_for,client_for,create_scope
pytestmark=pytest.mark.django_db(transaction=True)


def scoped_user(dataset,ids,name):
    user=user_for(dataset.tenant,name)
    for code in READ_PERMISSIONS:grant(user,code,scope_type='custom',config={'store_ids':ids})
    return user


def test_scoped_metadata_and_legacy_entry_protection(context):
    _,_,dataset,state=context
    ids=dataset.metadata['store_ids']
    user=scoped_user(dataset,ids,'scoped-reader')
    grant(user,'finance.import')
    dataset.metadata['checkpoint']={'private':'not-for-reader'};dataset.save()
    state.values={'html2-ledger-fees-v1':'private'};state.save()
    client=client_for(user)
    response=client.get(URL)
    assert response.status_code==200
    data=response.data['data']
    assert not data['can_edit'] and not data['can_view_settings']
    assert 'values' not in data and 'checkpoint' not in data['source']
    assert [row['id'] for row in data['scope_stores']]==ids
    assert data['rebuild_history']==[]
    for suffix in ['document/','report/']:
        assert client.get(URL+f'{dataset.pk}/'+suffix).status_code==403
    assert client.post(URL+f'{dataset.pk}/rebuild/',{'revision':0},format='json').status_code==403


def test_same_scope_shares_cache_and_revocation_blocks_finished_job(context,monkeypatch):
    _,_,dataset,_=context
    monkeypatch.setattr(run_calculation,'apply_async',Mock())
    ids=dataset.metadata['store_ids']
    first=scoped_user(dataset,ids,'scoped-one');second=scoped_user(dataset,ids,'scoped-two')
    query=Mock(return_value={'rows':[],'total':0})
    monkeypatch.setattr('apps.finance.summary_native.query',query)
    url=URL+f'{dataset.pk}/table/'
    a=client_for(first).get(url);b=client_for(second).get(url)
    assert a.status_code==b.status_code==202
    job=a.data['data']['job']['id']
    assert b.data['data']['job']['id']==job
    run_calculation(job)
    assert query.call_args.args[1]['filters']['_stores']==list(map(str,ids))
    assert client_for(second).get(URL+f'jobs/{job}/').status_code==200
    DataScope.objects.filter(role__user_roles__user=second).update(config={'store_ids':[]})
    assert client_for(second).get(URL+f'jobs/{job}/').status_code==403


def test_platform_and_store_intersection_and_full_cache_cannot_be_read(context,monkeypatch):
    client,_,dataset,_=context
    store=StoreMaster.objects.get(pk=dataset.metadata['store_ids'][0])
    other=StoreMaster.objects.create(tenant=dataset.tenant,platform=store.platform,code='other',name='Other',currency='PHP',country_code='PH')
    user=scoped_user(dataset,[store.pk],'scoped-platform')
    DataScope.objects.filter(role__user_roles__user=user).update(config={'platform_ids':[store.platform_id],'store_ids':[store.pk]})
    assert store_ids(user)==[store.pk]
    scoped=client_for(user)
    assert scoped.get(URL+f'{dataset.pk}/table/',{'filter_store':str(other.pk)}).status_code==403
    monkeypatch.setattr(run_calculation,'apply_async',Mock())
    fulljob=client.get(URL+f'{dataset.pk}/table/').data['data']['job']['id']
    assert scoped.get(URL+f'jobs/{fulljob}/').status_code==403
    _,_,foreign,_=create_scope('scope-foreign')
    DataScope.objects.filter(role__user_roles__user=user).update(config={'store_ids':[foreign.pk]})
    assert scoped.get(URL).status_code==403


def test_actor_revocation_blocks_execution_and_history_is_scoped(context,monkeypatch):
    _,_,dataset,_=context
    monkeypatch.setattr(run_calculation,'apply_async',Mock())
    user=scoped_user(dataset,dataset.metadata['store_ids'],'scoped-history')
    client=client_for(user)
    response=client.get(URL+f'{dataset.pk}/history/')
    job=FinanceSummaryCalculation.objects.get(pk=response.data['data']['job']['id'])
    assert job.request['filters']['_stores']==list(map(str,dataset.metadata['store_ids']))
    DataScope.objects.filter(role__user_roles__user=user).update(config={'store_ids':[]})
    query=Mock();monkeypatch.setattr('apps.finance.summary_native.query',query)
    assert run_calculation(job.pk)['status']=='blocked'
    assert not query.called


def test_unrepresentable_scope_does_not_become_platform_wide(context):
    _,_,dataset,_=context
    user=scoped_user(dataset,dataset.metadata['store_ids'],'scoped-currency')
    DataScope.objects.filter(role__user_roles__user=user).update(config={'store_ids':dataset.metadata['store_ids'],'currencies':['USD']})
    assert client_for(user).get(URL).status_code==403


def test_permission_resolution_is_once_per_request_and_revocation_is_fresh(context,monkeypatch):
    import apps.finance.summary_scopes as scopes
    _,_,dataset,_=context
    user=scoped_user(dataset,dataset.metadata['store_ids'],'scope-request-memo')
    resolver=Mock(wraps=scopes.get_permission_data_scopes)
    monkeypatch.setattr(scopes,'get_permission_data_scopes',resolver)
    client=client_for(user)
    assert client.get(URL,{'native':1}).status_code==200
    assert resolver.call_count==len(READ_PERMISSIONS)
    assert scopes._request_access.get() is None
    DataScope.objects.filter(role__user_roles__user=user).update(config={'store_ids':[]})
    assert client.get(URL,{'native':1}).status_code==403
    assert resolver.call_count==2*len(READ_PERMISSIONS)
    assert scopes._request_access.get() is None


def test_request_access_context_resets_on_failure(context):
    from types import SimpleNamespace
    from apps.finance.summary_scopes import request_access,request_context,_request_access
    _,user,_,_=context
    @request_access
    def broken(request):
        assert request_context(request.user) is not None
        raise RuntimeError('synthetic failure')
    with pytest.raises(RuntimeError):broken(SimpleNamespace(user=user))
    assert _request_access.get() is None
