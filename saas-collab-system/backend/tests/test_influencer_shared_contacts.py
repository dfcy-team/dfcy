from types import SimpleNamespace
import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers.models import (
    InfluenceArchiveGroup, InfluenceArchiveMembership, Influencer, InfluencerContact, InfluencerProfile,
)
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def records(code='shared'):
    tenant = Tenant.objects.create(code=code, name=code)
    user = CustomUser.objects.create_user(username=code, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=code, name=code)
    for grant in ('influencers.view', 'influencers.manage'):
        permission, _ = Permission.objects.get_or_create(code=grant, defaults={'name': grant, 'module': 'influencers', 'action': grant.split('.')[-1]})
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    scope = DataScope.objects.create(tenant=tenant, role=role, scope_type='all')
    members = []
    for platform, handle in [('tiktok', 'first.creator'), ('facebook', 'second.creator'), ('instagram', 'unrelated.creator')]:
        member = Influencer.objects.create(tenant=tenant, code=platform, name=platform, platform=platform, handle=handle)
        InfluencerProfile.objects.create(tenant=tenant, influencer=member, market='PH', display_name=platform)
        members.append(member)
    group = InfluenceArchiveGroup.objects.create(tenant=tenant, created_by=user, updated_by=user)
    for member in members[:2]:
        InfluenceArchiveMembership.objects.create(tenant=tenant, group=group, influencer=member, created_by=user)
    client = APIClient()
    client.force_authenticate(user)
    return SimpleNamespace(tenant=tenant, user=user, role=role, scope=scope, group=group,
                           a=members[0], b=members[1], unrelated=members[2], client=client)


def contact(record, member, value, **kwargs):
    return InfluencerContact.objects.create(tenant=record.tenant, influencer=member, created_by=record.user,
                                            channel='email', value=value, **kwargs)


def form(record, member):
    response = record.client.get(f'/api/internal/influencers/{member.pk}/', {'include_form': 'true'})
    assert response.status_code == 200, response.data
    return response.data['data']


def patch(record, member, contacts, *, version=None, legacy=False):
    return record.client.patch(
        f'/api/internal/influencers/{member.pk}/contacts/' if legacy else f'/api/internal/influencers/{member.pk}/?include_form=true',
        {'contacts': contacts}, format='json', HTTP_IF_MATCH=version or form(record, member)['updated_at'],
    )


def test_associated_forms_contacts_endpoint_and_detail_share_but_unrelated_and_foreign_do_not():
    r = records()
    contact(r, r.a, 'a@example.test', is_primary=True)
    contact(r, r.b, 'b@example.test')
    contact(r, r.unrelated, 'unrelated@example.test')
    other = records('foreign')
    contact(other, other.a, 'foreign@example.test')
    a, b = form(r, r.a), form(r, r.b)
    assert a['contacts'] == b['contacts']
    assert [c['value'] for c in a['contacts']] == ['a@example.test', 'b@example.test']
    assert a['contact_sharing'] == {'shared': True, 'conflicts': []}
    for member in (r.a, r.b):
        assert r.client.get(f'/api/internal/influencers/{member.pk}/contacts/').data['data'] == a['contacts']
        assert r.client.get(f'/api/internal/influencers/{member.pk}/').data['data']['contacts'] == a['contacts']
    assert form(r, r.unrelated)['contact_sharing']['shared'] is False
    assert r.client.get(f'/api/internal/influencers/{other.a.pk}/contacts/').status_code == 404


@pytest.mark.parametrize('legacy', [False, True])
def test_edit_delete_and_add_from_either_entry_updates_shared_pool_without_changing_accounts(legacy):
    r = records()
    first = contact(r, r.a, 'first@example.test', is_primary=True)
    removed = contact(r, r.b, 'removed@example.test')
    source_before = list(Influencer.objects.values('pk', 'platform', 'handle', 'name', 'status', 'cooperation_status'))
    profiles_before = list(InfluencerProfile.objects.values())
    response = patch(r, r.b, [
        {'channel': 'email', 'value': 'first@example.test', 'label': 'Shared remark'},
        {'channel': 'whatsapp', 'value': '+630000001', 'is_primary': True},
    ], legacy=legacy)
    assert response.status_code == 200, response.data
    a, b = form(r, r.a), form(r, r.b)
    assert a['contacts'] == b['contacts']
    assert {c['value'] for c in a['contacts']} == {'first@example.test', '+630000001'}
    first.refresh_from_db(); removed.refresh_from_db()
    assert first.label == 'Shared remark' and first.is_primary is False
    assert removed.is_active is False
    assert list(Influencer.objects.values('pk', 'platform', 'handle', 'name', 'status', 'cooperation_status')) == source_before
    assert list(InfluencerProfile.objects.values()) == profiles_before
    r.group.refresh_from_db()
    assert r.group.version == 2
    log = OperationLog.objects.get(action='shared_contacts_update')
    assert log.after_data['member_ids'] == [r.a.pk, r.b.pk]
    assert 'example.test' not in json.dumps([log.before_data, log.after_data])


@pytest.mark.parametrize('legacy', [False, True])
def test_shared_edit_advances_sibling_version_and_rejects_stale_editor(legacy):
    r = records()
    a_before = form(r, r.a)['updated_at']
    b_before = form(r, r.b)['updated_at']
    assert patch(r, r.b, [{'channel': 'email', 'value': 'shared@example.test'}], legacy=legacy).status_code == 200
    assert form(r, r.a)['updated_at'] != a_before
    assert form(r, r.b)['updated_at'] != b_before
    stale = patch(r, r.a, [], version=a_before, legacy=legacy)
    assert stale.status_code == 409
    assert [c['value'] for c in form(r, r.a)['contacts']] == ['shared@example.test']


def test_existing_duplicates_display_once_and_conflicting_remarks_are_explicit():
    r = records()
    contact(r, r.a, 'same@example.test', label='First remark', is_primary=True)
    contact(r, r.b, 'same@example.test', label='Other remark', is_primary=True)
    data = form(r, r.a)
    assert len(data['contacts']) == 1
    assert 'First remark' in data['contact_sharing']['conflicts'][0]
    assert 'Other remark' in data['contact_sharing']['conflicts'][0]
    assert InfluencerContact.objects.filter(is_active=True).count() == 2, 'Reading cannot mutate historical rows'
    result = patch(r, r.b, [{'channel': 'email', 'value': 'same@example.test', 'label': 'Confirmed', 'is_primary': True}])
    assert result.status_code == 200, result.data
    assert InfluencerContact.objects.filter(is_active=True).count() == 1
    assert form(r, r.a)['contact_sharing']['conflicts'] == []


def test_old_multiple_primary_contacts_require_explicit_resolution_and_failed_write_rolls_back():
    r = records()
    contact(r, r.a, 'a@example.test', is_primary=True)
    contact(r, r.b, 'b@example.test', is_primary=True)
    data = form(r, r.a)
    assert data['contact_sharing']['conflicts']
    before = list(InfluencerContact.objects.values())
    invalid = patch(r, r.a, [{'channel': 'email', 'value': 'a@example.test', 'is_primary': True},
                            {'channel': 'email', 'value': 'b@example.test', 'is_primary': True}])
    assert invalid.status_code == 400
    assert list(InfluencerContact.objects.values()) == before
    assert patch(r, r.a, [{'channel': 'email', 'value': 'a@example.test', 'is_primary': True},
                          {'channel': 'email', 'value': 'b@example.test'}]).status_code == 200
    assert form(r, r.a)['contact_sharing']['conflicts'] == []


def test_restricted_reader_cannot_see_hidden_sibling_contacts_or_replace_them():
    r = records()
    contact(r, r.a, 'visible@example.test')
    contact(r, r.b, 'hidden@example.test')
    profile = r.b.profile
    profile.market = 'MY'
    profile.save()
    warehouse = WarehouseMaster.objects.create(tenant=r.tenant, code='PH', name='PH', country_code='PH', warehouse_type='third_party')
    r.scope.scope_type = 'custom'
    r.scope.config = {'warehouse_ids': [warehouse.pk]}
    r.scope.save()
    assert [c['value'] for c in form(r, r.a)['contacts']] == ['visible@example.test']
    assert r.client.get(f'/api/internal/influencers/{r.b.pk}/contacts/').status_code == 404
    before = list(InfluencerContact.objects.values())
    assert patch(r, r.a, []).status_code == 403
    assert list(InfluencerContact.objects.values()) == before
    edited = r.client.patch(f'/api/internal/influencers/{r.a.pk}/?include_form=true',
        {'category': 'Local edit'}, format='json', HTTP_IF_MATCH=form(r, r.a)['updated_at'])
    assert edited.status_code == 200, edited.data
    assert list(InfluencerContact.objects.values()) == before


def test_new_related_archive_inherits_existing_contacts_without_copy_or_erasure():
    r = records()
    original = contact(r, r.a, 'existing@example.test', is_primary=True)
    response = r.client.post(f'/api/internal/influencers/{r.a.pk}/related-archives/',
        {'archive': {'platform': 'youtube', 'nickname_id': 'new.creator', 'contacts': []}},
        format='json', HTTP_IF_MATCH=form(r, r.a)['updated_at'])
    assert response.status_code == 201, response.data
    assert [c['value'] for c in response.data['data']['contacts']] == ['existing@example.test']
    assert response.data['data']['contact_sharing']['shared'] is True
    assert InfluencerContact.objects.get().pk == original.pk


def test_clearing_shared_pool_soft_disables_all_members_contacts():
    r = records()
    contact(r, r.a, 'a@example.test')
    contact(r, r.b, 'b@example.test')
    assert patch(r, r.b, []).status_code == 200
    assert form(r, r.a)['contacts'] == []
    assert form(r, r.b)['contacts'] == []
    assert InfluencerContact.objects.count() == 2
    assert not InfluencerContact.objects.filter(is_active=True).exists()


def test_contact_endpoint_requires_explicit_list_and_noop_does_not_advance_versions():
    r = records()
    contact(r, r.a, 'existing@example.test')
    a_before, b_before = form(r, r.a)['updated_at'], form(r, r.b)['updated_at']
    empty = r.client.patch(f'/api/internal/influencers/{r.b.pk}/contacts/', {}, format='json', HTTP_IF_MATCH=b_before)
    assert empty.status_code == 400
    assert patch(r, r.b, [{'channel': 'email', 'value': 'existing@example.test'}], legacy=True).status_code == 200
    assert form(r, r.a)['updated_at'] == a_before
    assert form(r, r.b)['updated_at'] == b_before
    assert not OperationLog.objects.filter(action='shared_contacts_update').exists()


def test_view_only_user_reads_shared_channels_but_cannot_modify_them():
    r = records()
    contact(r, r.a, 'existing@example.test')
    version = form(r, r.a)['updated_at']
    r.role.permissions.remove(Permission.objects.get(code='influencers.manage'))
    response = r.client.get(f'/api/internal/influencers/{r.b.pk}/contacts/')
    assert response.status_code == 200
    assert response.data['data'][0]['value'] == 'existing@example.test'
    assert patch(r, r.a, [], version=version, legacy=True).status_code == 403
