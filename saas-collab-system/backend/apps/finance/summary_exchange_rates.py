"""Retire only the imported HTML2 monthly quotes, retaining reversible audit evidence."""
from django.db import transaction

from .models import FinanceAuditLog
from .summary_models import FinanceSummaryInput
from .summary_service import require_access


def retire_html2_monthly_rates(user):
    require_access(user, write=True)
    with transaction.atomic():
        rows = list(FinanceSummaryInput.objects.select_for_update().filter(tenant=user.tenant,
            kind='exchange_rate', payload__basis='monthly', payload__quote__basis='warehouse_monthly',
            payload__quote__source='已确认月度业务汇率迁入SaaS').order_by('pk'))
        if not rows:
            return 0
        evidence = [{key: getattr(row, key) for key in ['id', 'source_key', 'period', 'payload',
                    'source_hash', 'source_description', 'created_by_id']} for row in rows]
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action='summary_legacy_fx_retired',
            object_type='finance_summary', object_id='monthly_rates',
            masked_detail={'replacement': 'SaaS完整自然月每日汇率算术平均', 'archived_rates': evidence})
        FinanceSummaryInput.objects.filter(tenant=user.tenant, pk__in=[row.pk for row in rows]).delete()
        return len(rows)
