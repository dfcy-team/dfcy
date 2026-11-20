"""Explicit file confirmation and a single immutable-source difference fee."""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from .warehouse_bill_contract import POLICY, is_file_policy, refresh_processing_difference
from .warehouse_fee_models import WarehouseBillUpload, WarehouseFee


def registration_guard(user, fee):
    if not is_file_policy(fee.source): return
    if fee.source.get('order_warehouse') and fee.kind == 'order':
        from .warehouse_bill_matching import LocalOrderLookup, apply_match
        from .warehouse_fee_services import content
        original = content(fee)
        checked = dict(original)
        source = dict(fee.source)
        lookup = LocalOrderLookup(user, [(checked, source)])
        error = apply_match(lookup, checked, source)
        if error or any(checked.get(k) != original.get(k) for k in ['warehouse_id', 'store_id', 'external_order_id']):
            raise ValidationError('订单或仓库关联已变化，请返回原文件重新核对。')
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
    if job.summary.get('mixed_warehouses'):
        return None
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
        if error or any(checked.get(k) != row.data.get(k) for k in ['store_id','external_order_id'] + (['warehouse_id'] if row.source.get('order_warehouse') else [])):
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
        job.summary['file_confirmation']['difference_pending'] = bool(
            job.summary.get('mixed_warehouses') and job.summary.get('difference_state') == 'confirmation_required'
            and not job.summary.get('difference_allocation'))
        job.summary['file_confirmation']['selected_count'] = len(rows)
    job.version += 1
    job.save(update_fields=['summary','version','updated_at'])
    return job


@transaction.atomic
def allocate_difference(user, job, payload):
    from decimal import Decimal, InvalidOperation
    from apps.tenants.models import Tenant
    from .warehouse_fee_services import require, create_fee, operate, hash_value
    require(user, 'register')
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    job = WarehouseBillUpload.objects.select_for_update().get(pk=job.pk, tenant=user.tenant)
    refresh_processing_difference(job.summary)
    summary = job.summary
    if type(payload.get('version')) is not int or payload['version'] != job.version or job.status not in {'ready', 'completed'}:
        raise ValidationError('任务版本或状态已变化，请刷新后核对。')
    if not summary.get('mixed_warehouses') or summary.get('difference_state') != 'confirmation_required':
        raise ValidationError('仅混仓正处理费差额需要分配。')
    if summary.get('validation', {}).get('blocking') or summary.get('correction_warning'):
        raise ValidationError('整批存在阻断项，请先核对。')
    if payload.get('coverage_confirmed') is not True or payload.get('difference_confirmed') is not True:
        raise ValidationError('请确认工作表覆盖和差额分配。')
    reason = payload.get('reason')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValidationError('请填写500字以内的分配依据。')
    if not job.rows.exists() or job.rows.exclude(fee__status='registered').exists():
        raise ValidationError('请先完成全部原文件明细登记，再分配差额。')
    entries = payload.get('allocations')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValidationError('请填写仓库分配金额。')
    amounts = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'warehouse_id', 'amount'}:
            raise ValidationError('分配字段无效。')
        warehouse = entry['warehouse_id']
        if type(warehouse) is not int or warehouse not in summary.get('warehouse_ids', []) or warehouse in amounts:
            raise ValidationError('只能分配至本账单仓库，且不能重复。')
        try:
            amount = Decimal(str(entry['amount']))
            if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -6:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValidationError('分配金额须为大于零、最多六位小数的数字。')
        amounts[warehouse] = amount
    if sum(amounts.values()) != Decimal(summary['processing_difference']):
        raise ValidationError('分配合计必须等于整单处理费差额。')
    formula = {k:summary[k] for k in ['file_total','effective_order_total','effective_other_total','processing_difference']}
    allocation = [{'warehouse_id':w,'amount':format(a.normalize(), 'f')} for w,a in sorted(amounts.items())]
    basis = hash_value([formula, allocation])
    receipt = summary.get('difference_allocation')
    if receipt:
        if receipt['basis'] != basis or WarehouseFee.objects.filter(tenant=user.tenant, pk__in=receipt['fee_ids'], status='registered').count() != len(receipt['fee_ids']):
            raise ValidationError('已有分配记录或费用状态发生变化，请核对原记录，不能重复分配。')
        return job
    if WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=job.file_hash, source__type='warehouse_file_supplement').exclude(status='void').exists():
        raise ValidationError('同一原文件已有差额记录，请核对原上传批次。')
    if WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=job.file_hash, reference__startswith='FILE-NET:').exclude(status='void').exists():
        raise ValidationError('同一原文件已有旧版补差，不能重复登记。')
    fees = []
    for entry in allocation:
        data = dict(kind='other',country=summary['country'],warehouse_id=entry['warehouse_id'],
            store_id=None,external_order_id='',bill_number=summary['bill_number'],bill_month=summary['bill_month'],
            fee_item='处理费差额',reference='FILE-PROCESSING:' + hash_value([job.file_hash, entry['warehouse_id']])[:40],
            amount=entry['amount'],currency='CNY',note=reason.strip())
        source = dict(type='warehouse_file_supplement',registration_mode=POLICY,job_id=str(job.pk),
            sha256=job.file_hash,file_name=job.file_name,formula=formula,allocation=allocation,reason=reason.strip(),actor=user.pk)
        fee, _ = create_fee(user, data, action='import', source=source)
        if fee.status == 'draft': fee = operate(user,fee.pk,'register',fee.version)
        if fee.status != 'registered': raise ValidationError('差额记录已失效，请核对原费用。')
        fees.append(fee.pk)
    summary['difference_allocation'] = dict(basis=basis,allocations=allocation,fee_ids=fees,actor=user.pk,reason=reason.strip())
    summary.setdefault('file_confirmation', {})['difference_pending'] = False
    job.version += 1
    job.save(update_fields=['summary','version','updated_at'])
    return job
