"""Current-source monthly reconstruction with currency defaults by document kind."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .cost_models import (PayableClassificationRecord, PaymentClassification, PaymentPlanRecord,
                          FeeRecord, SettlementRecord, PaymentCurrencyConfirmation)

ZERO = Decimal('0')
UNKNOWN = '币种未记录'
NATURES = ('corporate', 'personal')
FIELDS = ('opening_net', 'new_payable', 'paid_amount', 'historical_paid_amount', 'current_plan_amount')


def currency(value):
    value = str(value or '').strip().upper()
    return value if len(value) == 3 and value.isascii() and value.isalpha() else UNKNOWN


def monthly_currency(kind, *values):
    for value in values:
        code = currency(value)
        if code != UNKNOWN:
            return code
    return 'CNY' if kind in ('shipment', 'domestic_freight') else UNKNOWN


def allocations(amount, snapshot, supplemental):
    """Cash snapshot wins. Reject incomplete supplemental classifications as unknown."""
    nature = (snapshot or {}).get('nature')
    if nature in NATURES:
        return [(nature, amount)]
    try:
        rows = [(r['nature'], Decimal(str(r['amount']))) for r in supplemental or []]
        if rows and all(n in NATURES and a > ZERO for n, a in rows) and sum((a for _, a in rows), ZERO) == amount:
            return rows
    except (KeyError, ValueError, ArithmeticError, TypeError):
        pass
    return [('unknown', amount)]


def matches_party(saved, obj, default_party):
    return (saved.get('id') == obj['party_id'] and saved.get('type') == obj.get('party_type',default_party)
            and saved.get('name') == obj['party_name'])


def nature_balances(actor, kind, query, docs, display_payments, purchase_docs, start, end, *, plan_balance_cache=None):
    owner = {'shipment':'shipment_id','domestic_freight':'shipment_id','batch':'batch_id',
             'inbound':'inbound_id','purchase':'purchase_order_id'}[kind]
    default_party = 'supplier' if kind in ('shipment','purchase') else 'carrier'
    ids = list(docs)
    records = {getattr(r, owner): r for r in PayableClassificationRecord.objects.filter(
        tenant_id=actor.tenant_id, kind=kind, **{owner+'__in':ids})} if kind in ('shipment','domestic_freight','batch') else {}
    plans = list(PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind,
        **{owner+'__in':ids})) if kind in ('shipment','domestic_freight','batch') else []
    plan_by_id = {getattr(r, owner):r for r in plans}
    fee_rows = {getattr(r, owner):r.current_revision for r in FeeRecord.objects.filter(
        tenant_id=actor.tenant_id, **{owner+'__in':ids}).select_related('current_revision')} if kind in ('batch','inbound') else {}
    source_currencies = {}
    if kind in ('batch','domestic_freight'):
        field = 'freight_terms_snapshot' if kind == 'batch' else 'domestic_terms_snapshot'
        source_currencies = {pk:currency((snapshot or {}).get('currency')) for pk,snapshot in query.values_list('pk',field)}
    grouped = {}
    review_parties = set()

    def party(obj):
        return (obj.get('party_type',default_party), obj['party_id'])

    def matches(saved, obj):
        return matches_party(saved,obj,default_party)

    def add(obj, cur, nature, field, amount, source=''):
        if amount == ZERO: return
        key = (*party(obj), cur, nature, source if cur == UNKNOWN else '')
        row = grouped.setdefault(key, {'party_id':obj['party_id'],'party_type':party(obj)[0],
            'party_name':obj['party_name'] or '未指定往来单位','currency':cur,'nature':nature,
            'source_number':source if cur == UNKNOWN else '', **{f:ZERO for f in FIELDS}})
        row[field] += amount
        if nature == 'unknown' or cur == UNKNOWN: review_parties.add(party(obj))

    for pk,obj in docs.items():
        day = date.fromisoformat(obj['document_time'][:10]) if obj['document_time'] else None
        if obj['due'] is None or day is None:
            review_parties.add(party(obj)); continue
        if day >= end: continue
        due = Decimal(obj['due']); record = records.get(pk); plan = plan_by_id.get(pk)
        cur = source_currencies.get(pk,UNKNOWN)
        if cur == UNKNOWN:
            cur = currency(record.currency) if record and matches(record.party_snapshot,obj) else currency(plan.currency) if plan and matches(plan.party_snapshot,obj) else UNKNOWN
        cur = monthly_currency(kind, cur)
        valid = bool(record and record.payable_amount == due and matches(record.party_snapshot,obj)
                     and currency(record.currency) == cur)
        if record and not valid: review_parties.add(party(obj))
        fee = fee_rows.get(pk)
        if fee and fee.item_breakdown:
            split = allocations(due, {}, [item for item in fee.item_breakdown if Decimal(str(item.get('amount', '0'))) != ZERO])
        elif valid:
            split = [('corporate',record.corporate_amount),('personal',record.personal_amount),
                     ('unknown',due-record.corporate_amount-record.personal_amount)]
            if any(a < ZERO for _,a in split): split=[('unknown',due)]
        else: split=[('unknown',due)]
        for nature,amount in split:
            add(obj,cur,nature,'opening_net' if day < start else 'new_payable',amount,obj['number'])

    payment_rows = list(display_payments.filter(date__lt=end).select_related('reverses'))
    payment_ids = {p.reverses_id or p.pk for p in payment_rows}
    supplemental = {c.payment_id:c.allocations for c in PaymentClassification.objects.filter(
        tenant_id=actor.tenant_id,payment_id__in=payment_ids)}
    confirmed_currencies={r.payment_id:r.currency for r in PaymentCurrencyConfirmation.objects.filter(tenant_id=actor.tenant_id,payment_id__in=payment_ids)}
    covered = set()
    if kind == 'batch':
        from .batch_cash_classification import confirmed_groups
        for (batch_id, month, cur), (group, split) in confirmed_groups(actor.tenant_id, payment_rows).items():
            covered.update(p.pk for p in group)
            opening = month < start.isoformat()[:7]
            for nature, amount in split.items():
                add(docs[batch_id], cur, nature, 'opening_net' if opening else 'paid_amount',
                    -amount if opening else amount, docs[batch_id]['number'])
    for payment in payment_rows:
        if payment.pk in covered:
            continue
        obj = purchase_docs.get(payment.purchase_order_id) if kind == 'shipment' and payment.purchase_order_id else docs.get(getattr(payment,owner))
        if not obj: continue
        original = payment.reverses if payment.reverses_id else payment
        snapshot = original.account_snapshot or {}
        split = allocations(original.amount,snapshot,supplemental.get(original.pk))
        cur = monthly_currency(kind, snapshot.get('currency'), confirmed_currencies.get(original.pk))
        left = payment.amount
        for index,(nature,amount) in enumerate(split):
            part = left if index == len(split)-1 else (payment.amount * amount / original.amount).quantize(Decimal('0.0001'),rounding=ROUND_HALF_UP)
            left -= part
            signed = -part if payment.reverses_id else part
            add(obj,cur,nature,'opening_net' if payment.date < start else 'paid_amount',
                -signed if payment.date < start else signed,obj['number']+' / 付款'+str(original.pk))

    # Historical cumulative settlements are not cash transactions and remain a separate column.
    if kind in ('shipment','batch'):
        history = list(SettlementRecord.objects.filter(tenant_id=actor.tenant_id,
            **{owner+'__in':ids},current_revision__isnull=False).select_related('current_revision'))
        supplements = {c.settlement_revision_id:c.allocations for c in PaymentClassification.objects.filter(
            tenant_id=actor.tenant_id,settlement_revision_id__in=[r.current_revision_id for r in history])}
        history_currencies={r.settlement_revision_id:r.currency for r in PaymentCurrencyConfirmation.objects.filter(tenant_id=actor.tenant_id,settlement_revision_id__in=[r.current_revision_id for r in history])}
        for record in history:
            revision=record.current_revision
            if revision.date >= end or not revision.recorded_amount: continue
            obj=docs[getattr(record,owner)]
            rows=revision.payee_allocations or []
            try:
                valid=bool(rows and sum((Decimal(str(r['amount'])) for r in rows),ZERO)==revision.recorded_amount
                    and all(Decimal(str(r['amount']))>ZERO for r in rows))
            except (KeyError,ValueError,ArithmeticError,TypeError): valid=False
            if valid:
                parts=[(currency((r.get('account_snapshot') or {}).get('currency') or r.get('currency')),
                    (r.get('account_snapshot') or {}).get('nature') or r.get('nature'),Decimal(str(r['amount']))) for r in rows]
            else:
                parts=[(UNKNOWN,n,a) for n,a in allocations(revision.recorded_amount,{},supplements.get(revision.pk))]
            for cur,nature,amount in parts:
                cur = monthly_currency(kind, cur, history_currencies.get(revision.pk))
                add(obj,cur,nature if nature in NATURES else 'unknown',
                    'opening_net' if revision.date<start else 'historical_paid_amount',
                    -amount if revision.date<start else amount,obj['number']+' / 历史已付')

    from .payment_plan_links import line_balances
    for plan in plans:
        obj=docs[getattr(plan,owner)]
        if not matches(plan.party_snapshot,obj):
            review_parties.add(party(obj)); continue
        if not any(line.get('due_date') and start.isoformat() <= line['due_date'] < end.isoformat() for line in plan.lines or []):
            continue
        balances = plan_balance_cache.get(plan.pk) if plan_balance_cache is not None else None
        if balances is None:
            balances = line_balances(plan)
        for index, line in enumerate(plan.lines or []):
            balance = balances[str(line.get('line_id') or f'legacy-{plan.pk}-{index}')]
            if line.get('due_date') and start.isoformat()<=line['due_date']<end.isoformat():
                add(obj,monthly_currency(kind, plan.currency),line.get('nature') if line.get('nature') in NATURES else 'unknown',
                    'current_plan_amount',balance['remaining_amount'],obj['number'])
    result=[]
    for row in grouped.values():
        if all(row[field] == ZERO for field in FIELDS):
            continue
        opening=row.pop('opening_net')
        ending=opening+row['new_payable']-row['paid_amount']-row['historical_paid_amount']
        uncertain=(row['party_type'],row['party_id']) in review_parties
        row.update(opening_payable=None if uncertain else max(opening,ZERO),opening_credit=None if uncertain else max(-opening,ZERO),
                   reference_opening_payable=max(opening,ZERO),reference_opening_credit=max(-opening,ZERO),
                   remaining_amount=None if (row['party_type'],row['party_id']) in review_parties else max(ending,ZERO),
                   reference_remaining_amount=max(ending,ZERO),credit_balance=None if uncertain else max(-ending,ZERO),
                   reference_credit_balance=max(-ending,ZERO),
                   needs_review=(row['party_type'],row['party_id']) in review_parties or opening < ZERO or ending < ZERO)
        result.append({k:str(v) if isinstance(v,Decimal) else v for k,v in row.items()})
    return sorted(result,key=lambda r:(r['party_name'],r['party_type'],r['party_id'] or 0,r['currency'],r['nature'],r['source_number']))
