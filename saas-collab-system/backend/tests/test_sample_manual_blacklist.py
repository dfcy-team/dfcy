from types import SimpleNamespace
from decimal import Decimal

import pytest
from django.db.models import QuerySet

from apps.influencers.models import Influencer, InfluencerRestriction, SampleFulfillment
from apps.permissions.models import DataScope
from apps.tenants.models import Tenant
from tests.test_influencer_fulfillment import user_with_permissions, store_for

pytestmark = pytest.mark.django_db
PERMISSIONS = ("influencers.fulfillment.view", "influencers.fulfillment.manage", "influencers.manage")


def setup_data(codes=PERMISSIONS, scope=DataScope.ScopeType.ALL):
    tenant = Tenant.objects.create(name="Sample blacklist", code="sample-blacklist-state")
    user, client = user_with_permissions(tenant, "sample-blacklist-state", *codes, scope=scope)
    store = store_for(tenant, "blacklist")
    creator = Influencer.objects.create(tenant=tenant, code="creator", name="Creator", platform="TikTok", handle="blacklist.creator")
    samples = []
    for index in range(3):
        sample = SampleFulfillment.objects.create(tenant=tenant, influencer=creator, store=store, owner=user,
            fulfillment_no=f"YPDD{index}", request_key=f"key-{index}", request_hash="hash", calculated_cost="12.34")
        QuerySet.update(SampleFulfillment.objects.filter(pk=sample.pk), status="completed" if index==2 else "shipped")
        samples.append(sample)
    return SimpleNamespace(tenant=tenant, user=user, client=client, store=store, creator=creator, samples=samples)


def send(data, *, mode="patch", confirm=True, version=1, pk=None, **extra):
    url=f"/api/internal/influencers/sample-fulfillments/{pk or data.samples[0].pk}/"
    payload={"status":"blacklisted", "confirm_terminal":confirm, **extra}
    return getattr(data.client,mode)(url+('status/' if mode=='post' else ''),payload,format="json",HTTP_IF_MATCH=f'"{version}"')


@pytest.mark.parametrize("mode", ["patch","post"])
def test_manual_blacklist_updates_archive_and_open_samples_atomically(mode):
    data=setup_data()
    response=send(data,mode=mode)
    assert response.status_code==200,response.data
    assert response.data['data']['status']=='blacklisted'
    assert InfluencerRestriction.objects.get(tenant=data.tenant,influencer=data.creator).is_blacklisted
    for sample in data.samples[:2]:
        sample.refresh_from_db()
        assert sample.status=='blacklisted' and sample.version==2
        assert sample.calculated_cost==Decimal('12.34')
        assert sample.status_events.filter(to_status='blacklisted').count()==1
    data.samples[2].refresh_from_db()
    assert data.samples[2].status=='completed'
    assert not data.samples[2].status_events.exists()
    again=send(data,mode=mode,version=1)
    assert again.status_code==409
    assert data.creator.restrict_events.count()==1


@pytest.mark.parametrize('codes,scope',[
    (PERMISSIONS[:-1],DataScope.ScopeType.ALL),
    (PERMISSIONS,DataScope.ScopeType.OWN),
])
def test_missing_archive_permission_or_limited_scope_cannot_blacklist(codes,scope):
    data=setup_data(codes,scope)
    response=send(data)
    assert response.status_code==403,response.data
    assert not InfluencerRestriction.objects.exists()
    data.samples[0].refresh_from_db()
    assert data.samples[0].status=='shipped'


def test_confirmation_and_version_are_required_before_archive_mutation():
    data=setup_data()
    assert send(data,confirm=False).status_code==400
    assert send(data,version=999).status_code==409
    assert not InfluencerRestriction.objects.exists()


def test_terminal_and_other_tenant_records_are_not_blacklisted():
    data=setup_data()
    assert send(data,pk=data.samples[2].pk).status_code==400
    other=Tenant.objects.create(name="Other",code="other-sample-blacklist")
    other_creator=Influencer.objects.create(tenant=other,code="other",name="Other",platform="TikTok",handle="other")
    other_store=store_for(other,"other")
    other_user,_=user_with_permissions(other,"other-blacklist-user",*PERMISSIONS)
    sample=SampleFulfillment.objects.create(tenant=other,influencer=other_creator,store=other_store,owner=other_user,
        fulfillment_no="OTHER",request_key="OTHER",request_hash="hash")
    assert send(data,pk=sample.pk).status_code==404
    assert not InfluencerRestriction.objects.exists()


def test_fact_changes_roll_back_when_blacklist_permission_is_missing():
    data=setup_data(PERMISSIONS[:-1])
    response=send(data,notes="must roll back")
    assert response.status_code==403,response.data
    data.samples[0].refresh_from_db()
    assert data.samples[0].notes=='' and data.samples[0].version==1
    assert not InfluencerRestriction.objects.exists()


def test_archive_and_samples_roll_back_together_on_failure(monkeypatch):
    from apps.influencers import services
    data=setup_data()
    original=services.set_influencer_blacklist
    def fail(**kwargs):
        original(**kwargs)
        raise RuntimeError('simulated audit failure')
    monkeypatch.setattr(services,'set_influencer_blacklist',fail)
    with pytest.raises(RuntimeError,match='simulated audit failure'):
        send(data)
    assert not InfluencerRestriction.objects.exists()
    assert not data.creator.restrict_events.exists()
    for sample in data.samples[:2]:
        sample.refresh_from_db()
        assert sample.status=='shipped' and sample.version==1
        assert not sample.status_events.exists()
