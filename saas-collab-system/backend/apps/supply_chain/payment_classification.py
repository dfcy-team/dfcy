"""Audited corporate/personal labels for immutable legacy cash and opening entries."""
from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from . import costs, services
from .cost_models import PaymentClassification, PaymentRecord, SettlementRecord, SettlementRevision
from .models import domain_write
from .permissions import MANAGE, VIEW


def _parent(actor, kind, source_id, entry_type, entry_id, permission):
    source = costs._payment_owner(actor, kind, source_id, permission)
    if entry_type == 'payment':
        row = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, pk=entry_id).first()
        if row is None: raise NotFound('付款记录不存在。')
        expected = {'purchase': ('purchase_order_id', source.pk, 'goods'),
                    'shipment': ('shipment_id', source.pk, 'goods'),
                    'domestic_freight': ('shipment_id', source.pk, 'domestic_freight'),
                    'batch': ('batch_id', source.pk, 'goods'),
                    'inbound': ('inbound_id', source.pk, 'goods')}.get(kind)
        if not expected or getattr(row, expected[0]) != expected[1] or row.purpose != expected[2]:
            raise NotFound('付款记录不属于当前单据。')
        return source, row, row.amount
    if entry_type == 'opening':
        if kind not in ('shipment','batch'): raise NotFound('此单据无历史期初付款。')
        settlement = SettlementRecord.objects.filter(tenant_id=actor.tenant_id, **{kind:source}).select_related('current_revision').first()
        revision = settlement.current_revision if settlement and settlement.current_revision_id else None
        if not revision or revision.pk != entry_id: raise NotFound('历史期初记录不存在或已不是当前版本。')
        return source, revision, revision.recorded_amount
    raise NotFound('不支持的付款记录类型。')


def _authoritative(parent):
    if isinstance(parent, PaymentRecord):
        nature=(parent.account_snapshot or {}).get('nature')
        return ([{'nature':nature,'amount':str(parent.amount)}], True) if nature in ('corporate','personal') else (None,False)
    allocations=parent.payee_allocations or []
    try:
        values=[]
        for a in allocations:
            snapshot=a.get('account_snapshot') or {}
            nature=snapshot.get('nature') or a.get('nature')
            if nature not in ('corporate','personal') or Decimal(str(a.get('amount','0')))<=0: raise ValueError()
            values.append({'nature':nature,'amount':Decimal(str(a['amount']))})
        if values and sum((a['amount'] for a in values),Decimal(0))==parent.recorded_amount:
            combined={}
            for a in values: combined[a['nature']]=combined.get(a['nature'],Decimal(0))+a['amount']
            return ([{'nature':k,'amount':str(v)} for k,v in combined.items()],True)
    except Exception:
        pass
    return None,False


def _rows(actor, parent):
    return list(PaymentClassification.objects.filter(tenant_id=actor.tenant_id, **({'payment':parent} if isinstance(parent,PaymentRecord) else {'settlement_revision':parent})))


def classification_data(actor, kind, source_id, entry_type, entry_id):
    _source,parent,amount=_parent(actor,kind,source_id,entry_type,entry_id,VIEW)
    record=PaymentClassification.objects.filter(tenant_id=actor.tenant_id, **({'payment':parent} if isinstance(parent,PaymentRecord) else {'settlement_revision':parent})).first()
    authoritative,locked=_authoritative(parent)
    allocations=authoritative if locked else (record.allocations if record else [])
    amount=Decimal(amount)
    natures={x['nature'] for x in allocations}
    nature=next(iter(natures)) if len(natures)==1 and allocations else ('mixed' if len(natures)>1 else 'unclassified')
    editable=not locked
    try:
        costs._payment_owner(actor,kind,source_id,MANAGE)
    except (PermissionDenied,NotFound): editable=False
    if isinstance(parent,PaymentRecord) and (parent.reverses_id or parent.reversal.exists()): editable=False
    history=[]
    if record:
        events=services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,aggregate_type='paymentclassification',aggregate_id=record.pk,action='payment_classification_saved').order_by('created_at','pk')
        history=[{'created_at':e.created_at,'reason':e.payload.get('reason',''),'allocations':e.payload.get('allocations',[])} for e in events]
    return {'version':record.version if record else 0,'amount':str(amount),'allocations':allocations,'nature':nature,
            'can_edit':editable,'history':history,
            'message':'已有收款账户性质，沿用原分类。' if locked and isinstance(parent,PaymentRecord) else
                      '历史付款分类已由有效分配记录确定。' if locked else
                      '尚未确认，请核对原付款凭证后分类。' if not allocations else '请核对已保存的付款性质。'}


@transaction.atomic
def save_classification(actor,kind,source_id,entry_type,entry_id,payload,request_key):
    services._internal(actor); services._tenant_lock(actor)
    _source,parent,amount=_parent(actor,kind,source_id,entry_type,entry_id,MANAGE)
    authoritative,locked=_authoritative(parent)
    if locked: raise ValidationError('已有收款账户性质，不能覆盖原始分类。')
    allocations=[{'nature':row['nature'],'amount':str(row['amount'])} for row in payload['allocations']]
    if allocations:
        seen=set(); total=Decimal(0)
        for row in allocations:
            if row['nature'] in seen: raise ValidationError('对公或对私分类重复，请合并金额。')
            seen.add(row['nature']); total+=Decimal(row['amount'])
        if total!=Decimal(amount): raise ValidationError('对公和对私分类金额合计必须等于原付款金额。')
    reason=payload['reason'].strip()
    if not reason: raise ValidationError({'reason':'补充原因必填。'})
    owner={'payment':parent} if isinstance(parent,PaymentRecord) else {'settlement_revision':parent}
    record=PaymentClassification.objects.select_for_update().filter(tenant_id=actor.tenant_id,**owner).first()
    version=record.version if record else 0
    digest={'kind':kind,'source_id':source_id,'entry_type':entry_type,'entry_id':entry_id,'allocations':allocations,'reason':reason,'expected_version':payload['expected_version']}
    key=services._key(request_key)
    prior=services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,aggregate_type='paymentclassification',action='payment_classification_saved',request_key=key).first()
    if prior:
        services._matching_replay(prior,services.request_hash(digest));return
    if isinstance(parent,PaymentRecord) and (parent.reverses_id or parent.reversal.exists()):
        raise ValidationError('已冲销付款不可更改分类。')
    if version!=payload['expected_version']: raise ValidationError('付款分类已更新，请刷新后重试。')
    with domain_write():
        if record:
            before=record.allocations;record.allocations=allocations;record.reason=reason;record.version+=1;record.save()
        else:
            before=[];record=PaymentClassification.objects.create(tenant=actor.tenant,created_by=actor,allocations=allocations,reason=reason,version=1,**owner)
        services._event(actor,record,'payment_classification_saved',key,digest,audit={'before':before,'reason':reason})
