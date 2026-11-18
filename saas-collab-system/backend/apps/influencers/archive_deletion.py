"""Recoverable deletion of exactly one full platform archive, never its group."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError
from apps.audit.services import write_operation_log
from apps.tenants.models import Tenant
from .models import Influencer
from .platform_accounts import InfluencerFormConflict
from .scopes import filter_queryset, require_scope


@transaction.atomic
def change_archive_deletion(*, user, influencer_id, version, restore=False):
    require_scope(user, 'influencers.manage')
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    obj = get_object_or_404(filter_queryset(user, Influencer.objects.select_for_update(), 'influencers.manage'),
                            pk=influencer_id, tenant_id=user.tenant_id)
    try:
        expected = parse_datetime(version.strip().strip('"')) if isinstance(version, str) else None
    except ValueError:
        expected = None
    if expected is None or timezone.is_naive(expected):
        raise ValidationError({'If-Match': '请刷新档案后操作，需要当前版本。'})
    if obj.updated_at != expected:
        raise InfluencerFormConflict({'If-Match': '档案已被修改，请刷新后重试。'})
    if obj.is_deleted == (not restore):
        raise ValidationError({'is_deleted': '档案已恢复。' if restore else '档案已删除。'})
    before = {'is_deleted': obj.is_deleted, 'status': obj.status, 'platform': obj.platform}
    if restore:
        obj.status = obj.deletion_previous_status if obj.deletion_previous_status in Influencer.Status.values else Influencer.Status.INACTIVE
        obj.is_deleted = False
        obj.deleted_at = None
        obj.deletion_previous_status = ''
    else:
        obj.deletion_previous_status = obj.status
        obj.status = Influencer.Status.INACTIVE
        obj.is_deleted = True
        obj.deleted_at = timezone.now()
    obj.save(update_fields=['is_deleted', 'deleted_at', 'deletion_previous_status', 'status', 'updated_at'])
    write_operation_log(tenant=user.tenant, user=user, module='influencers',
        action='archive_restore' if restore else 'archive_soft_delete', object_type='influencer', object_id=obj.pk,
        before_data=before, after_data={'is_deleted':obj.is_deleted,'status':obj.status,'platform':obj.platform})
    return obj
