"""Reviewed source migration and explicit database-only reaggregation."""
import gzip
import hashlib
import json
import re

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import FinanceAuditLog
from .summary_models import FinanceSummaryDataset, FinanceSummaryState, FinanceSummaryInput
from .summary_service import document_path, engine, private_root, require_access, unpack_values, source_checkpoint
from .summary_database import collect
from .summary_database_document import render


def trusted_template(dataset):
    body = gzip.decompress(document_path(dataset).read_bytes())
    if hashlib.sha256(body).hexdigest() != dataset.source_hash:
        raise ValidationError('计算模板校验失败，未读取或迁移旧批次数据。')
    return body.decode('utf8')


def initialize_sources(dataset, user, scope):
    """Migrate historical evidence/reports; monthly FX is calculated from SaaS daily evidence."""
    require_access(user, write=True)
    html = trusted_template(dataset)
    snapshot = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', html)[1])
    base = re.search(r'<script>\s*([\s\S]*?)</script>', html)[1]
    historical = json.loads(re.search(r'const HISTORICAL_FX=(\{[^\n]+\});', base)[1])
    sp = json.loads(re.search(r'<script id="html2-sp6th-fees-data">globalThis.HTML2_SP6TH_FEES=(.*);\s*</script>', html)[1])
    historical.update(sp.get('fx') or {})
    created = 0
    with transaction.atomic():
        locked = FinanceSummaryDataset.objects.select_for_update().get(pk=dataset.pk, tenant=user.tenant, active=True)
        if locked.metadata.get('database_scope'):
            return
        for basis, rows in [('historical', historical)]:
            for key, value in rows.items():
                period = key.split('|')[0];quote = value
                _, fresh = FinanceSummaryInput.objects.get_or_create(tenant=user.tenant, kind='exchange_rate', source_key=key,
                    defaults={'period': period, 'payload': {'basis': basis, 'quote': quote}, 'source_hash': dataset.source_hash,
                              'source_description': '原已验收批次中用户确认的汇率，按条迁入；保留来源文件SHA256', 'created_by': user})
                created += fresh
        adjustment = snapshot.get('adjustment_events') or {}
        for row in adjustment.get('records') or []:
            # Marketing Fee is already stored in the official payout snapshots.
            if row.get('scope') != 'order':
                continue
            file = adjustment['files'][row['file']]
            key = file['sha256']+':'+str(row['row'])
            _, fresh = FinanceSummaryInput.objects.get_or_create(tenant=user.tenant, kind='adjustment', source_key=key,
                defaults={'store_id': adjustment['store_id'], 'period': adjustment['period'], 'payload': row,
                          'source_hash': file['sha256'], 'source_description': file['name']+' · '+file['sheet']+' · 行'+str(row['row']),
                          'created_by': user})
            created += fresh
        locked.metadata = {**locked.metadata, 'database_scope': scope}
        locked.save(update_fields=['metadata'])
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action='summary_source_migration',
            object_type='finance_summary', object_id=str(dataset.pk),
            masked_detail={'created_rows': created, 'source_hash': dataset.source_hash, 'scope': scope})
    return created


def rebuild(dataset, user, revision, *, publication_guard=None):
    require_access(user, write=True)
    scope = dataset.metadata.get('database_scope')
    if not scope:
        raise ValidationError('尚未完成原始汇率及调整来源迁移，未用旧快照代替数据库数据。')
    state = dataset.accounting_state
    if state.revision != revision:
        return None
    original_values = state.values
    # A consistent DB read; no provider requests, no source table writes.
    with transaction.atomic():
        initial_checkpoint = source_checkpoint(scope['stores'])
        source = collect(user, scope)
        checkpoint = source_checkpoint(scope['stores'])
        if checkpoint != initial_checkpoint:
            raise ValidationError('读取期间来源数据变化，请重试；未生成混合批次。')
    template = trusted_template(dataset)
    html = render(template, source).encode('utf8')
    digest = hashlib.sha256(html).hexdigest()
    file = private_root()/(digest+'.html.gz')
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(gzip.compress(html))
    candidate = FinanceSummaryDataset(document_file=file.name, source_hash=digest)
    values = unpack_values(original_values)
    info = engine(candidate, {'action': 'inspect', 'state': values})
    reports, month = [], scope['from'][:7]
    while month <= scope['to'][:7]:
        reports.append(engine(candidate, {'action': 'reconcile', 'month': month, 'state': values}))
        year, number = map(int, month.split('-'))
        month = f'{year + (number == 12):04d}-{number % 12 + 1:02d}'
    reconciliation = {'passed': all(report['passed'] for report in reports),
        'conservation_passed': all(report['passed'] for report in reports),
        'attribution_complete': all(report.get('attribution_complete', False) for report in reports),
        'attribution': [item for report in reports for item in report.get('attribution', [])],
        'checks': sum(report['checks'] for report in reports),
        'results': [result for report in reports for result in report['results']]}
    if not reconciliation['passed']:
        raise ValidationError('各级汇总未守恒，未切换当前批次。')
    with transaction.atomic():
        if publication_guard:
            publication_guard()
        user.refresh_from_db()
        if not user.is_active or user.user_type != 'internal' or user.tenant_id != dataset.tenant_id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('执行用户已失效，原批次保持有效。')
        require_access(user, write=True)
        if not FinanceSummaryDataset.objects.select_for_update().filter(pk=dataset.pk, tenant=user.tenant, active=True).exists():
            return None
        locked = FinanceSummaryState.objects.select_for_update().get(dataset=dataset)
        if locked.revision != revision or locked.values != original_values:
            return None
        if source_checkpoint(scope['stores']) != checkpoint:
            raise ValidationError('汇总期间来源数据发生变化，请重新汇总；原批次保持有效。')
        FinanceSummaryDataset.objects.filter(tenant=user.tenant, active=True).update(active=False)
        fresh = FinanceSummaryDataset.objects.create(tenant=user.tenant, created_by=user, source_hash=digest,
            document_file=file.name, label='财务汇总 · SaaS数据库重汇总 · '+scope['to'][:7],
            metadata={**info, 'data_origin': 'saas_database', 'database_scope': scope,
                'store_ids': scope['stores'], 'checkpoint': checkpoint, 'source_counts': source['source_counts'],
                'basis': '全部金额、商品归属、成本、汇率来自SaaS数据库；点击重新汇总读取最新来源；缺项保留待核',
                'previous_dataset': dataset.pk, 'reconciliation': reconciliation})
        FinanceSummaryState.objects.create(dataset=fresh, values=original_values, updated_by=user)
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action='summary_rebuild',
            object_type='finance_summary', object_id=str(fresh.pk),
            masked_detail={'previous_dataset': dataset.pk, 'source_hash': digest,
                           'source_counts': source['source_counts'], 'checks': reconciliation['checks']})
    return fresh
