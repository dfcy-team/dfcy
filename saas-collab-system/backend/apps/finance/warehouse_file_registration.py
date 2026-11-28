"""Explicit file confirmation and a single immutable-source difference fee."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from .warehouse_bill_contract import POLICY, is_file_policy, refresh_processing_difference
from .warehouse_fee_models import WarehouseBillUpload, WarehouseFee


def registration_guard(user, fee):
    if not is_file_policy(fee.source): return
    job = WarehouseBillUpload.objects.filter(tenant=user.tenant, pk=fee.source.get('job_id')).first()
    if not job or job.summary.get('validation', {}).get('blocking'):
        raise ValidationError('原文件批次存在阻断项，只能保留草稿，不能确认登记。')
    if not job.summary.get('file_confirmation', {}).get('coverage'):
        raise ValidationError('请在原文件工作台核对工作表覆盖后确认登记。')
    if job.summary.get('difference_state') == 'confirmation_required' and not job.summary['file_confirmation'].get('difference'):
        raise ValidationError('请先确认原文件正净差额，不能绕过补差核对。')


def supplement(user, job):
    from .warehouse_fee_services import create_fee, operate, hash_value
    if job.summary.get('difference_state') != 'confirmation_required': return None
    warehouse_id = job.summary.get('settlement_warehouse_id')
    if not warehouse_id: raise ValidationError('原文件补差仓库无法唯一确定，请先核对仓库。')
    reference = 'FILE-PROCESSING:' + hash_value([job.file_hash, warehouse_id])[:40]
    if WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=job.file_hash,
            reference__startswith='FILE-NET:').exclude(status='void').exists():
        raise ValidationError('本文件已有旧版结算补差，请先核对原记录，不能重复生成处理费差额。')
    # The hash, not the upload user or the current file name, identifies this fact.
    data = dict(kind='other',country=job.summary['country'],warehouse_id=warehouse_id,
        store_id=None,external_order_id='',bill_number=job.summary['bill_number'],
        bill_month=job.summary['bill_month'],fee_item='处理费差额',reference=reference,
        amount=job.summary['processing_difference'],currency='CNY',
        note='结算总额−全部订单明细合计−其他费用合计（不含本差额）；不随勾选或登记进度变化。')
    source = dict(type='warehouse_file_supplement',registration_mode=POLICY,job_id=str(job.pk),
        sha256=job.file_hash,file_name=job.file_name,formula={k:job.summary[k] for k in
        ['file_total','effective_order_total','effective_other_total','processing_difference']})
    fee, _ = create_fee(user, data, action='import', source=source)
    if fee.status == 'draft': fee = operate(user, fee.pk, 'register', fee.version)
    return fee


@transaction.atomic
def confirm_rows(user, job, payload, *, register=True):
    from apps.tenants.models import Tenant
    from .warehouse_fee_services import require, create_fee, operate
    from .warehouse_bill_matching import LocalOrderLookup, apply_match
    require(user, 'register' if register else 'import')
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    job = WarehouseBillUpload.objects.select_for_update().get(pk=job.pk)
    refresh_processing_difference(job.summary)
    if type(payload.get('version')) is not int or job.version != payload['version'] or job.status not in {'ready','completed'}:
        raise ValidationError('任务版本或状态已变化，请刷新后核对。')
    if job.summary.get('correction_warning'):
        raise ValidationError('人工修正无法对应原始行，请先核对修正冲突。')
    if register and job.summary.get('validation', {}).get('blocking'):
        raise ValidationError('整批存在阻断项，禁止确认登记及补差。')
    if register and payload.get('coverage_confirmed') is not True:
        raise ValidationError('请确认工作表覆盖与原文件依据。')
    if register and job.summary.get('difference_state') == 'confirmation_required' and payload.get('difference_confirmed') is not True:
        raise ValidationError('请确认正净差额及是否遗漏项目。')
    numbers = payload.get('rows')
    if not isinstance(numbers, list) or not 1 <= len(numbers) <= 500 or any(type(n) is not int for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValidationError('请明确选择1至500行，不允许重复行号。')
    rows = list(job.rows.select_for_update().filter(number__in=numbers).order_by('number'))
    if len(rows) != len(numbers) or any(r.status not in {'valid','created','existing'} for r in rows):
        raise ValidationError('所选行包含异常或已失效记录，请重新核对。')
    if register:
        job.summary['file_confirmation'] = {'coverage':True,'difference':payload.get('difference_confirmed') is True,
                                             'actor':user.pk,'version':job.version}
        job.save(update_fields=['summary','updated_at'])
    lookup = LocalOrderLookup(user, [(r.data,r.source) for r in rows])
    from .warehouse_bill_edits import provenance_conflicts
    conflicts = provenance_conflicts(user, job, [r for r in rows if not r.fee_id])
    for row in rows:
        if row.number in conflicts: raise ValidationError('原文件该行已有其他导入记录，请核对来源，不能重复登记。')
        checked = dict(row.data)
        error = apply_match(lookup, checked, dict(row.source))
        if error or any(checked.get(k) != row.data.get(k) for k in ['store_id','external_order_id']):
            raise ValidationError('订单关联已变化，请重新匹配。')
        if row.fee_id:
            fee = WarehouseFee.objects.select_for_update().get(pk=row.fee_id,tenant=user.tenant)
        else:
            fee, _ = create_fee(user,row.data,action='import',source=row.source)
        if fee.status == 'void': raise ValidationError('费用已作废，不能重复登记。')
        if register and fee.status == 'draft': fee = operate(user,fee.pk,'register',fee.version)
        row.fee, row.status = fee, 'created' if fee.status == 'draft' else 'existing'
        row.save(update_fields=['fee','status'])
    if register:
        difference_fee = supplement(user,job)
        job.summary['file_confirmation']['supplement_id'] = difference_fee.pk if difference_fee else None
        job.summary['file_confirmation']['selected_count'] = len(rows)
    job.version += 1
    job.save(update_fields=['summary','version','updated_at'])
    return job
