import re
from decimal import Decimal
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from . import costs, services
from .cost_models import PaymentCurrencyConfirmation, PaymentRecord, SettlementRecord
from .models import domain_write
from .payment_classification import _parent
from .permissions import MANAGE, VIEW


def _account_currency(parent):
    value=(parent.account_snapshot or {}).get('currency') if isinstance(parent, PaymentRecord) else ''
    return value if isinstance(value,str) and re.fullmatch(r'[A-Z]{3}',value,flags=re.ASCII) else ''


def _opening_currency(parent):
    allocations=parent.payee_allocations or []
    found=[]
    try:
        for item in allocations:
            c=(item.get('account_snapshot') or {}).get('currency') or item.get('currency')
            amount=Decimal(str(item.get('amount','0')))
            if not isinstance(c,str) or not re.fullmatch(r'[A-Z]{3}',c,flags=re.ASCII) or amount<=0: return ''
            found.append((c,amount))
        if found and len({c for c,_ in found})==1 and sum((a for _,a in found),Decimal(0))==parent.recorded_amount:
            return found[0][0]
    except Exception: pass
    return ''


def _opening_mixed(parent):
    currencies={(a.get('account_snapshot') or {}).get('currency') or a.get('currency') for a in (parent.payee_allocations or [])}
    currencies.discard(None);currencies.discard('')
    return len(currencies)>1


def payment_currency(actor, kind, source_id, entry_type, entry_id):
    _,parent,_=_parent(actor,kind,source_id,entry_type,entry_id,VIEW)
    return _account_currency(parent) or (_opening_currency(parent) if entry_type=='opening' else '')


def currency_data(actor,kind,source_id,entry_type,entry_id):
    _,parent,_=_parent(actor,kind,source_id,entry_type,entry_id,VIEW)
    is_reversal=isinstance(parent,PaymentRecord) and bool(parent.reverses_id)
    if is_reversal:
        parent=PaymentRecord.objects.get(tenant_id=actor.tenant_id,pk=parent.reverses_id)
    owner={'payment':parent} if isinstance(parent,PaymentRecord) else {'settlement_revision':parent}
    record=PaymentCurrencyConfirmation.objects.filter(tenant_id=actor.tenant_id,**owner).first()
    authoritative=_account_currency(parent) or (_opening_currency(parent) if entry_type=='opening' else '')
    editable=not bool(authoritative)
    try: costs._payment_owner(actor,kind,source_id,MANAGE)
    except (PermissionDenied,NotFound): editable=False
    if is_reversal or (entry_type=='opening' and _opening_mixed(parent)): editable=False
    history=[]
    if record:
        events=services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,aggregate_type='paymentcurrencyconfirmation',aggregate_id=record.pk,action='payment_currency_saved').order_by('created_at','pk')
        history=[{'created_at':e.created_at,'reason':e.payload.get('reason',''),'currency':e.payload.get('currency')} for e in events]
    return {'currency':authoritative or (record.currency if record else None),'version':record.version if record else 0,'can_edit':editable,'history':history,
        'message':'历史累计包含多个币种，不能整笔确认，请逐项核对。' if entry_type=='opening' and _opening_mixed(parent) else '原付款币种已确定。' if authoritative else ('请核对历史凭证并确认币种。' if not record else '请核对已保存的币种确认。')}


@transaction.atomic
def save_currency(actor,kind,source_id,entry_type,entry_id,payload,request_key):
    services._internal(actor); services._tenant_lock(actor)
    _,parent,_=_parent(actor,kind,source_id,entry_type,entry_id,MANAGE)
    if entry_type=='opening' and _opening_mixed(parent): raise ValidationError('期初付款分配币种不一致，不能按单笔确认币种。')
    if isinstance(parent,PaymentRecord) and (parent.reverses_id or parent.reversal.exists()):
        if parent.reverses_id: raise ValidationError('冲销付款不可更改币种。')
        # Original payment remains confirmable after reversal.
    owner={'payment':parent} if isinstance(parent,PaymentRecord) else {'settlement_revision':parent}
    record=PaymentCurrencyConfirmation.objects.select_for_update().filter(tenant_id=actor.tenant_id,**owner).first()
    version=record.version if record else 0
    digest={'kind':kind,'source_id':source_id,'entry_type':entry_type,'entry_id':entry_id,'currency':payload['currency'],'reason':payload['reason'].strip(),'expected_version':payload['expected_version']}
    key=services._key(request_key)
    prior=services.BusinessEvent.objects.filter(tenant_id=actor.tenant_id,aggregate_type='paymentcurrencyconfirmation',action='payment_currency_saved',request_key=key).first()
    if prior: services._matching_replay(prior,services.request_hash(digest));return
    authoritative=_account_currency(parent) or (_opening_currency(parent) if entry_type=='opening' else '')
    if authoritative: raise ValidationError('原付款币种已确定，不能覆盖。')
    if entry_type=='opening':
        known={(a.get('account_snapshot') or {}).get('currency') or a.get('currency') for a in parent.payee_allocations or []}
        known={c for c in known if isinstance(c,str) and re.fullmatch(r'[A-Z]{3}',c,flags=re.ASCII)}
        if any(c!=payload['currency'] for c in known):
            raise ValidationError('确认币种与已有付款分配币种不一致。')
    if version!=payload['expected_version']: raise ValidationError('币种记录已更新，请刷新后重试。')
    with domain_write():
        if record:
            record.currency=digest['currency'];record.reason=digest['reason'];record.version+=1;record.save()
        else: record=PaymentCurrencyConfirmation.objects.create(tenant=actor.tenant,created_by=actor,currency=digest['currency'],reason=digest['reason'],version=1,**owner)
        services._event(actor,record,'payment_currency_saved',key,digest,audit={'currency':record.currency,'reason':record.reason})
