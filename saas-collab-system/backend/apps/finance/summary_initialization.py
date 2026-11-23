"""Explicit, tenant-scoped first calculation; candidates never publish themselves."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from .summary_models import FinanceSummaryDataset, FinanceSummaryState, FinanceSummaryCalculation
from .summary_service import private_root, require_access, has_full_scope, source_checkpoint

TEMPLATE_ROOT = Path(__file__).with_name('templates')


def template_bytes():
    manifest = json.loads((TEMPLATE_ROOT / 'database-v1.json').read_text(encoding='utf-8'))
    raw = gzip.decompress((TEMPLATE_ROOT / 'database-v1.html.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest() != manifest['sha256']:
        raise ValidationError('计算模板校验失败，未创建试算。')
    return raw, manifest


def runtime_status():
    node = shutil.which(getattr(settings, 'FINANCE_SUMMARY_NODE', None) or 'node')
    root = private_root()
    try:
        _, manifest = template_bytes()
        template = manifest['version']
    except (OSError, ValueError, KeyError, ValidationError):
        template = None
    missing = []
    if not node or not Path(node).is_file():
        missing.append('node')
    if not root.is_dir() or not os.access(root, os.W_OK):
        missing.append('private_storage')
    if not template:
        missing.append('calculation_template')
    return {'ready': not missing, 'missing': missing, 'template_version': template}


def initialization_status(user):
    from apps.masterdata.models import StoreMaster
    require_access(user)
    runtime = runtime_status()
    job = FinanceSummaryCalculation.objects.filter(tenant=user.tenant,
        request__bootstrap=True).order_by('-pk').values('id', 'status', 'error_code', 'result_dataset_id', 'created_at', 'finished_at', 'request').first()
    if job:
        job['scope'] = job.pop('request').get('scope', {})
    return {'initialized': False, 'status': 'uninitialized' if runtime['ready'] else 'runtime_missing',
        'runtime': runtime, 'can_edit': has_full_scope(user, 'finance.import'), 'initialization_job': job,
        'scope_stores': list(StoreMaster.objects.filter(tenant=user.tenant).order_by('code').values('id', 'code'))}


def request_initialization(user, scope):
    from apps.tenants.models import Tenant
    from .summary_maintenance import validate_scope
    from .summary_jobs import request_calculation
    require_access(user, write=True)
    scope = validate_scope(user, scope, None)
    if not runtime_status()['ready']:
        raise ValidationError('计算运行依赖尚未就绪，未创建试算任务。')
    raw, manifest = template_bytes()
    digest = manifest['sha256']
    file = private_root() / (digest + '.html.gz')
    # Immutable, data-free code template. Every tenant reads the same verified bytes.
    if not file.exists():
        temp = file.with_suffix('.tmp-' + os.urandom(8).hex())
        temp.write_bytes(gzip.compress(raw))
        os.replace(temp, file)
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        if FinanceSummaryDataset.objects.filter(tenant=user.tenant, active=True).exists():
            raise ValidationError('已有有效批次，请使用重新汇总或扩大范围。')
        seed, _ = FinanceSummaryDataset.objects.get_or_create(tenant=user.tenant, source_hash=digest,
            defaults={'active': False, 'label': '初始化计算模板（不含业务数据）', 'document_file': file.name,
                'created_by': user, 'metadata': {'bootstrap_template': True, 'template_version': manifest['version']}})
        FinanceSummaryState.objects.get_or_create(dataset=seed, defaults={'updated_by': user})
        return request_calculation(seed, user, {'bootstrap': True, 'scope': scope}, kind='rebuild')


def publish_candidate(user, pk):
    from apps.tenants.models import Tenant
    from .models import FinanceAuditLog
    from .summary_service import document_path
    require_access(user, write=True)
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        from django.shortcuts import get_object_or_404
        candidate = get_object_or_404(FinanceSummaryDataset.objects.select_for_update(), pk=pk, tenant=user.tenant)
        if not candidate.metadata.get('bootstrap_candidate'):
            raise ValidationError('该批次不是初始化候选批次。')
        if candidate.active:
            return candidate
        if FinanceSummaryDataset.objects.filter(tenant=user.tenant, active=True).exists():
            raise ValidationError('有效批次已变化，请刷新；未覆盖现有结果。')
        from .summary_jobs import current_dataset
        job = FinanceSummaryCalculation.objects.filter(tenant=user.tenant, result_dataset=candidate,
            status='ready', request__bootstrap=True).first()
        if not job or not current_dataset(job):
            raise ValidationError('候选计算规则已变化，请重新试算；未发布旧结果。')
        if not candidate.metadata.get('reconciliation', {}).get('conservation_passed'):
            raise ValidationError('候选试算未通过金额守恒核对，不能发布。')
        if not candidate.metadata.get('reconciliation', {}).get('attribution_complete'):
            raise ValidationError('候选试算仍有成本或费用待归属，不能发布；请核对缺项后重新试算。')
        if not candidate.metadata.get('source_checks', {}).get('coverage_complete'):
            raise ValidationError('候选试算存在未获取或待核来源，不能按零费用发布；请补齐来源后重新试算。')
        raw = gzip.decompress(document_path(candidate).read_bytes())
        if hashlib.sha256(raw).hexdigest() != candidate.source_hash:
            raise ValidationError('候选试算文件校验失败。')
        scope = candidate.metadata['database_scope']
        if source_checkpoint(scope['stores']) != candidate.metadata['checkpoint']:
            raise ValidationError('试算后来源数据已变化，请重新试算；未发布旧结果。')
        candidate.active = True
        candidate.save(update_fields=['active'])
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, action='summary_initialize_publish',
            object_type='finance_summary', object_id=str(candidate.pk),
            masked_detail={'source_hash': candidate.source_hash, 'scope': scope,
                'conservation_passed': True, 'attribution_complete': candidate.metadata['reconciliation']['attribution_complete']})
        return candidate
