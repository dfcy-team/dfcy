"""Database-only summary scheduling and explicitly reviewed coverage changes."""
from datetime import date, timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .summary_models import FinanceSummaryDataset, FinanceSummaryCalculation
from .summary_service import require_access, source_checkpoint, document_path


def validate_scope(user, value, previous):
    from apps.masterdata.models import StoreMaster
    if not isinstance(value, dict) or set(value) != {'from', 'to', 'stores'}:
        raise ValidationError('请提供开始日期、结束日期和店铺范围。')
    try:
        start, end = date.fromisoformat(value['from']), date.fromisoformat(value['to'])
        ids = value['stores']
        if not isinstance(ids, list) or not ids or any(type(pk) is not int for pk in ids):
            raise ValueError()
        if start > end or end > timezone.localdate() or len(ids) != len(set(ids)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError('汇总日期或店铺范围无效，结束日期不能晚于今天。') from None
    if StoreMaster.objects.filter(tenant=user.tenant, pk__in=ids).count() != len(ids):
        raise ValidationError('店铺不属于当前租户。')
    # A new batch replaces the active workspace; narrowing would hide history.
    if start > date.fromisoformat(previous['from']) or end < date.fromisoformat(previous['to']) or not set(previous['stores']).issubset(ids):
        raise ValidationError('扩大范围必须保留已有账期和店铺；重算历史账期请使用原范围。')
    return {'from': start.isoformat(), 'to': end.isoformat(), 'stores': sorted(ids)}


def schedule_changed_summaries():
    """Refresh the current/previous month only, preserving historical inputs."""
    from .summary_jobs import request_calculation
    from .summary_recent import recent_scope
    for dataset in FinanceSummaryDataset.objects.filter(active=True).select_related('accounting_state__updated_by'):
        scope = dataset.metadata.get('database_scope')
        if not scope or not cache.add(f'finance-summary-check:{dataset.pk}', True, 300):
            continue
        actor = dataset.accounting_state.updated_by
        try:
            if not actor.is_active or actor.tenant_id != dataset.tenant_id:
                continue
            require_access(actor, write=True)
            document_path(dataset)
            with transaction.atomic():
                locked = FinanceSummaryDataset.objects.select_for_update().get(pk=dataset.pk)
                if not locked.active:
                    continue
                jobs = FinanceSummaryCalculation.objects.filter(dataset=dataset, kind='rebuild')
                if jobs.filter(status__in=['queued', 'running']).exists() or jobs.filter(
                    status='failed', finished_at__gte=timezone.now()-timedelta(minutes=5)).exists():
                    continue
                checkpoint = source_checkpoint(scope['stores'])
                recent = recent_scope(scope['stores'])
                if checkpoint != dataset.metadata.get('checkpoint') or dataset.metadata.get('automatic_scope') != recent:
                    request_calculation(dataset, actor, {'revision': dataset.accounting_state.revision,
                        'automatic_scope': recent}, kind='rebuild')
        except (PermissionDenied, ValidationError):
            # Invalid authorization/files must not switch the accepted batch.
            continue
