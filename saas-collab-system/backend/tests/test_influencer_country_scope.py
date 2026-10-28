import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.permissions.models import Role, Permission, DataScope, UserRole
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.influencers.models import Influencer, InfluencerProfile, OutreachTask, SampleFulfillment, SampleItem
from apps.influencers.scopes import filter_queryset, allowed_countries

pytestmark = pytest.mark.django_db
ROOT = '/api/internal/influencers/'


@pytest.fixture
def scoped():
    tenant = Tenant.objects.create(code='country-scope', name='Country scope')
    user = CustomUser.objects.create_user(username='country-editor', tenant=tenant, user_type='internal')
    role = Role.objects.create(tenant=tenant, code='country-editor', name='Country editor')
    codes = ['influencers.view', 'influencers.manage', 'influencers.outreach.view',
             'influencers.outreach.manage', 'influencers.fulfillment.view', 'influencers.fulfillment.manage', 'influencers.catalog.view']
    for code in codes:
        p, _ = Permission.objects.get_or_create(code=code, defaults={'name': code, 'module': 'influencers', 'action': code.rsplit('.', 1)[-1]})
        role.permissions.add(p)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    platform = PlatformMaster.objects.create(tenant=tenant, code='tk', name='TikTok')
    other_platform = PlatformMaster.objects.create(tenant=tenant, code='sh', name='Shopee')
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code='ph', name='PH', country_code='PH', warehouse_type='third_party')
    outside_warehouse = WarehouseMaster.objects.create(tenant=tenant, code='th', name='TH', country_code='TH', warehouse_type='third_party', service_platform=platform)
    scope = DataScope.objects.create(tenant=tenant, role=role, scope_type='custom', config={'platform_ids': [platform.pk], 'warehouse_ids': [warehouse.pk]})
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code='ph', name='PH', country_code='PH')
    outside_store = StoreMaster.objects.create(tenant=tenant, platform=platform, code='th', name='TH', country_code='TH')
    cross_platform_store = StoreMaster.objects.create(tenant=tenant, platform=other_platform, code='shph', name='Shopee PH', country_code='PH')
    creators = []
    for i, (market, platform_name) in enumerate([('菲律宾', 'tiktok'), ('PH', 'shopee'), ('泰国', 'tiktok'), ('', 'tiktok'), ('MY、PH', 'tiktok')]):
        row = Influencer.objects.create(tenant=tenant, code=f'c{i}', name=f'C{i}', platform=platform_name)
        InfluencerProfile.objects.create(tenant=tenant, influencer=row, market=market)
        creators.append(row)
    client = APIClient(); client.force_authenticate(user)
    return locals()


def test_archives_share_country_not_platform_and_unknown_market_hidden(scoped):
    d = scoped
    assert allowed_countries(d['user'], 'influencers.view') == {'PH'}
    assert set(filter_queryset(d['user'], Influencer.objects.all(), 'influencers.view').values_list('pk', flat=True)) == {d['creators'][i].pk for i in (0, 1, 4)}
    response = d['client'].get(ROOT)
    assert response.status_code == 200, response.data
    assert {r['id'] for r in response.data['data']['results']} == {d['creators'][i].pk for i in (0, 1, 4)}
    for i in (2, 3):
        assert d['client'].get(f'{ROOT}{d["creators"][i].pk}/').status_code == 404
        assert d['client'].patch(f'{ROOT}{d["creators"][i].pk}/', {'name': 'blocked'}, format='json').status_code == 404


def test_all_scope_unchanged_and_no_cross_tenant(scoped):
    d = scoped; d['scope'].scope_type = 'all'; d['scope'].config = {}; d['scope'].save()
    other = Tenant.objects.create(code='other-country', name='Other')
    Influencer.objects.create(tenant=other, code='secret', name='Secret', platform='tiktok')
    assert filter_queryset(d['user'], Influencer.objects.all(), 'influencers.view').count() == 5


def test_operational_records_keep_platform_store_and_warehouse_limits(scoped):
    d = scoped
    tasks = []
    for n, store in enumerate([d['store'], d['outside_store'], d['cross_platform_store']]):
        tasks.append(OutreachTask.objects.create(tenant=d['tenant'], task_no=f't{n}', store=store, owner=d['user'], dispatcher=d['user']))
    visible = filter_queryset(d['user'], OutreachTask.objects.all(), 'influencers.outreach.view')
    assert list(visible.values_list('pk', flat=True)) == [tasks[0].pk]
    for path in ('outreach-tasks/', 'sample-fulfillments/', 'sample-fulfillment-options/', 'outreach-task-options/'):
        r = d['client'].get(ROOT + path)
        assert r.status_code == 200, (path, r.data)
    assert d['client'].get(f'{ROOT}outreach-tasks/{tasks[1].pk}/').status_code == 404
    for n, warehouse in enumerate([d['warehouse'], d['outside_warehouse']]):
        f = SampleFulfillment.objects.create(tenant=d['tenant'], fulfillment_no=f'f{n}', request_key=f'r{n}', request_hash='test', influencer=d['creators'][0], store=d['store'], owner=d['user'])
        SampleItem.objects.create(tenant=d['tenant'], fulfillment=f, warehouse=warehouse, site_code='PH', requested_sku='SKU', quantity=1)
    r = d['client'].get(ROOT + 'sample-fulfillments/')
    assert r.status_code == 200, r.data
    assert [row['fulfillment_no'] for row in r.data['data']['results']] == ['f0']


def test_profile_write_requires_authorized_market_and_cannot_reassign(scoped):
    d = scoped
    for market in ('', 'TH', 'PH、TH'):
        r = d['client'].post(ROOT, {'code': 'new', 'name': 'New', 'platform': 'shopee', 'profile': {'market': market}}, format='json')
        assert r.status_code == 400, r.data
    r = d['client'].post(ROOT, {'code': 'new', 'name': 'New', 'platform': 'shopee', 'profile': {'market': 'PH'}}, format='json')
    assert r.status_code == 201, r.data
    row = d['creators'][0]
    r = d['client'].patch(f'{ROOT}{row.pk}/', {'profile': {'market': 'TH'}}, format='json', HTTP_IF_MATCH=row.updated_at.isoformat())
    assert r.status_code == 400, r.data
    row.profile.refresh_from_db(); assert row.profile.market == '菲律宾'


def test_no_action_or_no_warehouse_does_not_grant_access(scoped):
    d = scoped
    d['role'].permissions.remove(Permission.objects.get(code='influencers.view'))
    assert d['client'].get(ROOT).status_code == 403
    d['scope'].config = {'platform_ids': [d['platform'].pk]}; d['scope'].save()
    assert d['client'].get(ROOT + 'sample-fulfillments/').status_code == 403


def test_nickname_draft_requires_permitted_store_and_gets_country(scoped):
    d = scoped
    r = d['client'].post(ROOT + 'resolve/', {'nickname': 'Country draft'}, format='json')
    assert r.status_code == 400, r.data
    r = d['client'].post(ROOT + 'resolve/', {'nickname': 'Country draft', 'store_id': d['outside_store'].pk}, format='json')
    assert r.status_code == 404, r.data
    r = d['client'].post(ROOT + 'resolve/', {'nickname': 'Country draft', 'store_id': d['store'].pk}, format='json')
    assert r.status_code == 201, r.data
    assert InfluencerProfile.objects.get(influencer_id=r.data['data']['id']).market == 'PH'


def test_task_target_list_detail_and_progress_use_same_country_scope(scoped):
    from apps.influencers.models import OutreachTarget
    d = scoped
    task = OutreachTask.objects.create(tenant=d['tenant'], task_no='mixed', store=d['store'], owner=d['user'], dispatcher=d['user'])
    for i in (0, 2):
        OutreachTarget.objects.create(tenant=d['tenant'], task=task, influencer=d['creators'][i])
    detail = d['client'].get(f'{ROOT}outreach-tasks/{task.pk}/')
    progress = d['client'].get(f'{ROOT}outreach-tasks/{task.pk}/progress/')
    targets = d['client'].get(f'{ROOT}outreach-tasks/{task.pk}/targets/')
    assert detail.status_code == progress.status_code == targets.status_code == 200
    assert detail.data['data']['linked_count'] == progress.data['data']['linked_count'] == 1
    assert len(targets.data['data']['results']) == 1
    rows = d['client'].get(ROOT + 'outreach-tasks/').data['data']['results']
    assert rows[0]['linked_count'] == 1
