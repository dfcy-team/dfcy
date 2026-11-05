from types import SimpleNamespace
from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.tenants.models import Tenant
from apps.influencers.models import Influencer, InfluencerProfile, InfluencerContact, InfluencerRestriction, InfluenceArchiveGroup, InfluenceArchiveMembership
from apps.influencers.platform_accounts import save_influencer_aggregate
from apps.influencers.archive_associations import archive_group_data
from apps.influencers.services import _tenant_influencer
from tests.test_influencer_platform_accounts import _records

pytestmark = pytest.mark.django_db


def endpoint(obj):
    return f'/api/internal/influencers/{obj.pk}/archive-deletion/'


def test_delete_only_one_platform_preserves_shared_group_and_contacts():
    r = _records('delete-one')
    fb = Influencer.objects.create(tenant=r.tenant, code='fb', name='FB', platform='facebook', handle='facebook.account')
    group = InfluenceArchiveGroup.objects.create(tenant=r.tenant, created_by=r.user, updated_by=r.user)
    for obj in (r.influencer, fb):
        InfluenceArchiveMembership.objects.create(tenant=r.tenant, group=group, influencer=obj, created_by=r.user)
    contact = InfluencerContact.objects.create(tenant=r.tenant, influencer=fb, channel='email', value='demo@example.test', created_by=r.user)
    version = fb.updated_at.isoformat()
    response = r.client.delete(endpoint(fb), HTTP_IF_MATCH=version)
    assert response.status_code == 200
    fb.refresh_from_db(); r.influencer.refresh_from_db(); contact.refresh_from_db()
    assert fb.is_deleted and fb.status == 'inactive' and fb.deleted_at
    assert not r.influencer.is_deleted and r.influencer.status == 'active'
    assert contact.is_active and InfluenceArchiveMembership.objects.filter(group=group).count() == 2
    assert OperationLog.objects.filter(tenant=r.tenant, object_id=str(fb.pk), action='archive_soft_delete').count() == 1
    visible = archive_group_data(r.influencer, user=r.user)
    assert [a['id'] for a in visible['related_archives']] == [r.influencer.pk]
    listing = r.client.get('/api/internal/influencers/', {'include_nickname_id': 'true'})
    assert listing.status_code == 200 and listing.data['data']['count'] == 1
    trash = r.client.get('/api/internal/influencers/', {'deleted_only': 'true', 'include_nickname_id': 'true'})
    assert trash.status_code == 200 and [a['id'] for a in trash.data['data']['results']] == [fb.pk]
    result = r.client.post(endpoint(fb), HTTP_IF_MATCH=fb.updated_at.isoformat())
    assert result.status_code == 200
    fb.refresh_from_db(); assert not fb.is_deleted and fb.deleted_at is None and fb.status == 'active'
    assert len(archive_group_data(r.influencer, user=r.user)['related_archives']) == 2


@pytest.mark.parametrize('status', ['active', 'inactive'])
def test_restore_original_status_and_keep_blacklist(status):
    r = _records('restore-status')
    r.influencer.status = status; r.influencer.save(update_fields=['status'])
    restriction = InfluencerRestriction.objects.create(tenant=r.tenant, influencer=r.influencer, is_blacklisted=True, created_by=r.user)
    assert r.client.delete(endpoint(r.influencer), HTTP_IF_MATCH=r.influencer.updated_at.isoformat()).status_code == 200
    r.influencer.refresh_from_db()
    assert r.client.post(endpoint(r.influencer), HTTP_IF_MATCH=r.influencer.updated_at.isoformat()).status_code == 200
    r.influencer.refresh_from_db(); restriction.refresh_from_db()
    assert r.influencer.status == status and restriction.is_blacklisted


def test_version_is_required_and_stale_rejected_without_change():
    r = _records('delete-version')
    assert r.client.delete(endpoint(r.influencer)).status_code == 400
    old = (r.influencer.updated_at - timedelta(seconds=1)).isoformat()
    assert r.client.delete(endpoint(r.influencer), HTTP_IF_MATCH=old).status_code == 409
    r.influencer.refresh_from_db(); assert not r.influencer.is_deleted
    assert not OperationLog.objects.filter(action='archive_soft_delete').exists()


def test_deleted_archive_cannot_be_reenabled_edited_or_linked():
    r = _records('deleted-guards')
    assert r.client.delete(endpoint(r.influencer), HTTP_IF_MATCH=r.influencer.updated_at.isoformat()).status_code == 200
    r.influencer.refresh_from_db()
    version = r.influencer.updated_at.isoformat()
    assert r.client.post(f'/api/internal/influencers/{r.influencer.pk}/status/', {'status':'active'}, format='json', HTTP_IF_MATCH=version).status_code == 400
    assert r.client.patch(f'/api/internal/influencers/{r.influencer.pk}/', {'name':'modified'}, format='json', HTTP_IF_MATCH=version).status_code == 400
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        save_influencer_aggregate(user=r.user, payload={'name':'modified'}, influencer_id=r.influencer.pk, expected_updated_at=version)
    with pytest.raises(ValidationError):
        _tenant_influencer(r.user, r.influencer.pk, for_update=False)
    r.influencer.refresh_from_db(); assert r.influencer.is_deleted and r.influencer.name == 'Creator'


def test_tenant_and_permission_boundaries():
    r = _records('delete-owner')
    other = _records('delete-other')
    denied = _records('delete-viewonly', permissions=('influencers.view',))
    assert r.client.delete(endpoint(other.influencer), HTTP_IF_MATCH=other.influencer.updated_at.isoformat()).status_code == 404
    assert denied.client.delete(endpoint(denied.influencer), HTTP_IF_MATCH=denied.influencer.updated_at.isoformat()).status_code == 403
    other.influencer.refresh_from_db(); denied.influencer.refresh_from_db()
    assert not other.influencer.is_deleted and not denied.influencer.is_deleted


def test_preserve_task_sample_and_cost_after_delete():
    from apps.masterdata.models import PlatformMaster, StoreMaster
    from apps.influencers.models import OutreachTask, SampleFulfillment
    r = _records('delete-history')
    platform = PlatformMaster.objects.create(tenant=r.tenant, code='tt', name='TikTok', platform_type='tiktok')
    store = StoreMaster.objects.create(tenant=r.tenant, code='demo', name='Demo', platform=platform, country_code='PH', currency='PHP')
    task = OutreachTask.objects.create(tenant=r.tenant, task_no='DRJL0001', influencer=r.influencer,
        store=store, dispatcher=r.user, owner=r.user)
    sample = SampleFulfillment.objects.create(tenant=r.tenant, fulfillment_no='YPDD0001', request_key='demo',
        request_hash='a'*64, influencer=r.influencer, outreach_task=task, store=store,
        owner=r.user, calculated_cost='12.3400')
    task_before = OutreachTask.objects.filter(pk=task.pk).values().get()
    sample_before = SampleFulfillment.objects.filter(pk=sample.pk).values().get()
    response = r.client.delete(endpoint(r.influencer), HTTP_IF_MATCH=r.influencer.updated_at.isoformat())
    assert response.status_code == 200
    assert OutreachTask.objects.filter(pk=task.pk).values().get() == task_before
    assert SampleFulfillment.objects.filter(pk=sample.pk).values().get() == sample_before


def test_deleted_metadata_cannot_be_written_through_normal_serializer():
    r = _records('delete-metadata')
    response = r.client.patch(f'/api/internal/influencers/{r.influencer.pk}/',
        {'is_deleted':True,'deleted_at':timezone.now().isoformat()}, format='json', HTTP_IF_MATCH=r.influencer.updated_at.isoformat())
    assert response.status_code in (200,400)
    r.influencer.refresh_from_db()
    assert not r.influencer.is_deleted and r.influencer.deleted_at is None
