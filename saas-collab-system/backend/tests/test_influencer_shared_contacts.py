from types import SimpleNamespace
import json

import pytest
from django.db.models import QuerySet
from django.utils import timezone
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


def test_private_contact_search_is_post_only_exact_scoped_and_read_only():
    r = records('contact-search')
    contact(r, r.a, 'Exact@Example.test', is_active=True)
    contact(r, r.b, 'hidden@example.test', is_active=False)
    contact(r, r.unrelated, 'other@example.test', is_active=True)
    before = list(InfluencerContact.objects.values('pk', 'is_active', 'value'))
    response = r.client.post('/api/internal/influencers/contact-search/?page_size=1',
                             {'channel': 'email', 'value': 'exact@example.TEST'}, format='json')
    assert response.status_code == 200, response.data
    rows = response.data['data']['results']
    assert response.data['data']['count'] == 2
    assert len(rows) == 1 and rows[0]['id'] in {r.a.pk, r.b.pk}
    assert response.data['data'].get('next')
    assert 'Exact@Example.test' not in json.dumps(response.data)
    assert all('Exact@Example.test' not in link for link in response.data.get('links', {}).values() if isinstance(link, str))
    assert all('exact@example.TEST' not in link for link in response.data.get('links', {}).values() if isinstance(link, str))
    assert list(InfluencerContact.objects.values('pk', 'is_active', 'value')) == before
    leaked_query = r.client.post('/api/internal/influencers/contact-search/?value=Exact%40Example.test',
                                 {'channel': 'email', 'value': 'exact@example.TEST'}, format='json')
    assert leaked_query.status_code == 400
    assert 'Exact@Example.test' not in json.dumps(leaked_query.data)
    assert 'exact@example.TEST' not in json.dumps(leaked_query.data)
    assert r.client.get('/api/internal/influencers/contact-search/').status_code == 405
    invalid = r.client.post('/api/internal/influencers/contact-search/',
                            {'channel': 'email', 'value': 'x' * 241}, format='json')
    assert invalid.status_code == 400 and 'value' not in json.dumps(invalid.data)


def test_contact_search_channel_only_phone_normalization_and_permission_scope():
    r = records('contact-channel-only')
    phone = InfluencerContact.objects.create(tenant=r.tenant, influencer=r.a, created_by=r.user,
                                            channel='phone', value='+63 (900) 123-4567', is_active=True)
    inactive = InfluencerContact.objects.create(tenant=r.tenant, influencer=r.b, created_by=r.user,
                                                channel='phone', value='+63 900 123 4567', is_active=False)
    contact(r, r.unrelated, '   ', is_active=True)
    response = r.client.post('/api/internal/influencers/contact-search/',
                             {'channel': 'phone', 'value': '+63-900-123-4567'}, format='json')
    assert response.status_code == 200, response.data
    assert {item['id'] for item in response.data['data']['results']} == {r.a.pk, r.b.pk}
    channel_only = r.client.post('/api/internal/influencers/contact-search/',
                                 {'channel': 'phone'}, format='json')
    assert channel_only.status_code == 200, channel_only.data
    assert {item['id'] for item in channel_only.data['data']['results']} == {r.a.pk, r.b.pk}
    r.role.permissions.remove(Permission.objects.get(code='influencers.manage'))
    view_only = r.client.post('/api/internal/influencers/contact-search/',
                              {'channel': 'phone', 'value': '+63-900-123-4567'}, format='json')
    assert view_only.status_code == 200
    grant = Permission.objects.get(code='influencers.view')
    r.role.permissions.remove(grant)
    r.role.permissions.add(Permission.objects.get(code='influencers.manage'))
    denied = r.client.post('/api/internal/influencers/contact-search/',
                           {'channel': 'phone', 'value': '+63-900-123-4567'}, format='json')
    assert denied.status_code == 403
    phone.refresh_from_db(); inactive.refresh_from_db()
    assert phone.is_active and not inactive.is_active


@pytest.mark.parametrize(('channel', 'stored', 'query'), [
    ('email', 'Exact@Example.test', 'exact@example.TEST'),
    ('phone', '+63 (900) 123-4567', '+63-900-123-4567'),
    ('whatsapp', '@Creator.123', 'creator.123'),
    ('viber', 'abc123', '@ABC123'),
])
def test_contact_search_channel_normalization(channel, stored, query):
    r = records(f'contact-normalize-{channel}')
    InfluencerContact.objects.create(tenant=r.tenant, influencer=r.a, created_by=r.user,
                                    channel=channel, value=stored, is_active=True)
    response = r.client.post('/api/internal/influencers/contact-search/',
                             {'channel': channel, 'value': query}, format='json')
    assert response.status_code == 200, response.data
    assert {row['id'] for row in response.data['data']['results']} == {r.a.pk, r.b.pk}
    assert stored not in json.dumps(response.data)


def test_contact_search_lowercase_normalization_is_exact_for_sharp_s_and_accents():
    r = records('contact-unicode-normalize')
    sharp_s = contact(r, r.a, 'straße@example.test', is_active=True)
    accented = contact(r, r.unrelated, 'café@example.test', is_active=True)
    exact = r.client.post('/api/internal/influencers/contact-search/',
                          {'channel': 'email', 'value': 'STRAßE@example.test'}, format='json')
    near_miss = r.client.post('/api/internal/influencers/contact-search/',
                              {'channel': 'email', 'value': 'cafe@example.test'}, format='json')
    accent_exact = r.client.post('/api/internal/influencers/contact-search/',
                                 {'channel': 'email', 'value': 'café@example.test'}, format='json')
    assert {row['id'] for row in exact.data['data']['results']} == {r.a.pk, r.b.pk}
    assert near_miss.data['data']['count'] == 0
    assert {row['id'] for row in accent_exact.data['data']['results']} == {r.unrelated.pk}
    assert sharp_s.value and accented.value


def test_contact_search_independently_scopes_hidden_owner_hidden_member_foreign_tenant_and_deleted_filter():
    r = records('contact-scope')
    r.scope.delete()
    warehouse = WarehouseMaster.objects.create(tenant=r.tenant, code='PH', name='PH', country_code='PH', warehouse_type='third_party')
    DataScope.objects.create(tenant=r.tenant, role=r.role, scope_type='custom', config={'warehouse_ids': [warehouse.pk]})
    r.a.profile.market = 'PH'; r.a.profile.save(update_fields=['market'])
    r.b.profile.market = 'MY'; r.b.profile.save(update_fields=['market'])
    contact(r, r.a, 'visible@example.test', is_active=True)
    contact(r, r.b, 'hidden-owner@example.test', is_active=True)
    assert r.client.post('/api/internal/influencers/contact-search/',
                         {'channel': 'email', 'value': 'hidden-owner@example.test'}, format='json').data['data']['count'] == 0
    visible = r.client.post('/api/internal/influencers/contact-search/',
                            {'channel': 'email', 'value': 'visible@example.test'}, format='json')
    assert {row['id'] for row in visible.data['data']['results']} == {r.a.pk}
    r.b.profile.market = 'PH'; r.b.profile.save(update_fields=['market'])
    deleted = Influencer.objects.get(pk=r.b.pk)
    QuerySet.update(Influencer.objects.filter(pk=deleted.pk), is_deleted=True, status='inactive', deleted_at=timezone.now())
    regular = r.client.post('/api/internal/influencers/contact-search/',
                            {'channel': 'email', 'value': 'visible@example.test'}, format='json')
    deleted_only = r.client.post('/api/internal/influencers/contact-search/?deleted_only=true',
                                 {'channel': 'email', 'value': 'visible@example.test'}, format='json')
    assert {row['id'] for row in regular.data['data']['results']} == {r.a.pk}
    assert {row['id'] for row in deleted_only.data['data']['results']} == {r.b.pk}
    other = records('contact-scope-foreign')
    contact(other, other.a, 'visible@example.test', is_active=True)
    foreign_search = r.client.post('/api/internal/influencers/contact-search/',
                                   {'channel': 'email', 'value': 'visible@example.test'}, format='json')
    assert {row['id'] for row in foreign_search.data['data']['results']} == {r.a.pk}


@pytest.mark.parametrize('payload', [
    [], {'channel': [], 'value': 'x'}, {'channel': 'x' * 41, 'value': 'x'},
    {'channel': 'not-a-channel', 'value': 'x'}, {'channel': 'email', 'value': 'x' * 241},
    {'channel': 'phone', 'value': '---'},
])
def test_contact_search_rejects_invalid_payloads_without_echoing_private_values(payload):
    r = records('contact-invalid-' + str(len(str(payload))))
    response = r.client.post('/api/internal/influencers/contact-search/', payload, format='json')
    assert response.status_code == 400
    assert 'x' * 20 not in json.dumps(response.data)


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


@pytest.mark.parametrize('contacts', [[], [{'channel': 'email', 'value': 'new@example.test'}]])
def test_restricted_country_can_create_archive_with_shared_contacts(contacts):
    r = records('restricted-create')
    r.scope.delete()
    warehouse = WarehouseMaster.objects.create(
        tenant=r.tenant, code='PH', name='Philippines', country_code='PH', warehouse_type='third_party',
    )
    DataScope.objects.create(
        tenant=r.tenant, role=r.role, scope_type='custom', config={'warehouse_ids': [warehouse.pk]},
    )
    response = r.client.post('/api/internal/influencers/?include_form=true', {
        'platform': 'youtube', 'handle': 'new.creator', 'name': 'New Creator',
        'profile': {'market': 'PH'}, 'contacts': contacts,
    }, format='json')
    assert response.status_code == 201, response.data
    created = Influencer.objects.get(tenant=r.tenant, handle='new.creator')
    assert created.profile.market == 'PH'
    assert list(InfluencerContact.objects.filter(influencer=created).values_list('value', flat=True)) == [
        item['value'] for item in contacts
    ]


def test_restricted_country_rejects_invalid_archive_without_residue():
    r = records('restricted-invalid-create')
    r.scope.delete()
    warehouse = WarehouseMaster.objects.create(
        tenant=r.tenant, code='PH', name='Philippines', country_code='PH', warehouse_type='third_party',
    )
    DataScope.objects.create(
        tenant=r.tenant, role=r.role, scope_type='custom', config={'warehouse_ids': [warehouse.pk]},
    )
    before = (Influencer.objects.filter(tenant=r.tenant).count(), InfluencerProfile.objects.filter(tenant=r.tenant).count(), InfluencerContact.objects.filter(tenant=r.tenant).count())
    response = r.client.post('/api/internal/influencers/?include_form=true', {
        'platform': 'youtube', 'handle': 'invalid.creator', 'name': 'Invalid Creator',
        'profile': {'market': 'MY'}, 'contacts': [{'channel': 'email', 'value': 'new@example.test'}],
    }, format='json')
    assert response.status_code == 400, response.data
    assert (Influencer.objects.filter(tenant=r.tenant).count(), InfluencerProfile.objects.filter(tenant=r.tenant).count(), InfluencerContact.objects.filter(tenant=r.tenant).count()) == before


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
