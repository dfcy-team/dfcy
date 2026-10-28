"""Contact sharing for explicitly associated archives, never platform identities."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.services import write_operation_log
from .models import InfluenceArchiveGroup, InfluenceArchiveMembership, Influencer, InfluencerContact
from .scopes import filter_queryset, require_object


def contact_member_ids(influencer):
    membership = InfluenceArchiveMembership.objects.filter(
        tenant_id=influencer.tenant_id, influencer_id=influencer.pk,
        group__tenant_id=influencer.tenant_id,
    ).first()
    if membership is None:
        return [influencer.pk]
    return list(InfluenceArchiveMembership.objects.filter(
        tenant_id=influencer.tenant_id, group_id=membership.group_id,
        influencer__tenant_id=influencer.tenant_id,
    ).order_by('influencer_id').values_list('influencer_id', flat=True))


def read_shared_contacts(*, user, influencer, permission_code):
    member_ids = contact_member_ids(influencer)
    visible_ids = filter_queryset(
        user, Influencer.objects.filter(pk__in=member_ids), permission_code,
    ).values('pk')
    rows = InfluencerContact.objects.filter(
        tenant_id=influencer.tenant_id, influencer_id__in=visible_ids, is_active=True,
    ).order_by('-is_primary', 'id')
    unique, labels = {}, defaultdict(set)
    for row in rows:
        key = (row.channel, row.value)
        unique.setdefault(key, row)
        labels[key].add(row.label)
    contacts = list(unique.values())
    conflicts = []
    if sum(row.is_primary for row in contacts) > 1:
        conflicts.append('关联档案存在多个主渠道，请保留一个后再保存联系方式。')
    for (channel, value), variants in labels.items():
        if len(variants) > 1:
            descriptions = ' / '.join(label or '无备注' for label in sorted(variants))
            conflicts.append(f'{channel} {value} 的历史备注不同：{descriptions}。请核实后保存。')
    return contacts, {'shared': len(member_ids) > 1, 'conflicts': conflicts}


def shared_contact_plans(*, user, influencer, payload):
    from .platform_accounts import _contact_plans

    if 'contacts' not in payload:
        return [], []
    member_ids = contact_member_ids(influencer)
    members = list(Influencer.objects.select_for_update().filter(
        tenant_id=user.tenant_id, pk__in=member_ids,
    ).order_by('pk'))
    # An explicit replacement requires access to every member, even for no-ops.
    for member in members:
        require_object(user, member, 'influencers.manage')
    rows = InfluencerContact.objects.select_for_update().filter(
        tenant_id=user.tenant_id, influencer_id__in=member_ids,
    ).order_by('-is_active', '-is_primary', 'id')
    existing, duplicates = {}, []
    for row in rows:
        key = (row.channel, row.value)
        if key in existing:
            if row.is_active or row.is_primary:
                duplicates.append((row, {'is_active': False, 'is_primary': False}))
        else:
            existing[key] = row
    plans = sorted(_contact_plans(payload, existing) + duplicates,
                   key=lambda plan: bool(plan[1].get('is_primary', False)))
    return plans, member_ids


def advance_shared_contact_versions(*, user, influencer, member_ids):
    from .platform_accounts import InfluencerFormConflict

    if len(member_ids) < 2:
        return
    membership = InfluenceArchiveMembership.objects.get(tenant_id=user.tenant_id, influencer_id=influencer.pk)
    group = InfluenceArchiveGroup.objects.select_for_update().get(tenant_id=user.tenant_id, pk=membership.group_id)
    members = list(Influencer.objects.select_for_update().filter(
        tenant_id=user.tenant_id, pk__in=member_ids,
    ).order_by('pk'))
    advanced = max(timezone.now(), group.updated_at + timedelta(microseconds=1),
                   *(row.updated_at + timedelta(microseconds=1) for row in members))
    for member in members:
        # Version changes must not invoke platform identity fanout through save().
        if QuerySet.update(Influencer.objects.filter(
            tenant_id=user.tenant_id, pk=member.pk, updated_at=member.updated_at,
        ), updated_at=advanced) != 1:
            raise InfluencerFormConflict()
    old_version = group.version
    if QuerySet.update(InfluenceArchiveGroup.objects.filter(
        tenant_id=user.tenant_id, pk=group.pk, version=old_version, updated_at=group.updated_at,
    ), version=old_version + 1, updated_at=advanced, updated_by_id=user.pk) != 1:
        raise InfluencerFormConflict()
    influencer.updated_at = advanced
    write_operation_log(
        tenant=user.tenant, user=user, module='influencers', action='shared_contacts_update',
        object_type='influencer_archive_group', object_id=group.pk,
        before_data={'group_version': old_version},
        after_data={'group_version': old_version + 1, 'member_ids': member_ids},
    )
