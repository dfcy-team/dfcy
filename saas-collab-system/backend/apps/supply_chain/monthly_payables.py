"""Scoped monthly reconstruction from current obligations and dated cash events."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Case, F, Q, Sum, When
from rest_framework import serializers
from rest_framework.response import Response

from .dashboard import MONEY, ZERO, _money_targets, scope
from .dates import business_date
from .document_time import document_time
from .models import PaymentApplication, PaymentRecord, PaymentVoucher, SettlementRecord
from .views import InternalAPI

KINDS = {'supplier': 'shipment', 'domestic': 'domestic_freight', 'carrier': 'batch',
         'clearance': 'inbound', 'deposit': 'purchase'}
OWNERS = {'supplier': 'shipment_id', 'domestic': 'shipment_id', 'carrier': 'batch_id',
          'clearance': 'inbound_id', 'deposit': 'purchase_order_id'}
AMOUNTS = ('opening_payable', 'new_payable', 'paid_amount', 'applied_amount',
           'historical_paid_amount', 'remaining_amount', 'opening_credit', 'credit_balance',
           'unknown_payment_amount')
D0 = Decimal('0')


class MonthlyQuery(serializers.Serializer):
    queue = serializers.ChoiceField(choices=tuple(KINDS), default='supplier')
    month = serializers.RegexField(r'^\d{4}-(0[1-9]|1[0-2])$', required=False)
    country_id = serializers.IntegerField(min_value=1, required=False)
    party_type = serializers.ChoiceField(choices=('supplier', 'carrier'), required=False)
    party_id = serializers.IntegerField(min_value=1, required=False)
    unassigned_party = serializers.BooleanField(default=False)
    view = serializers.ChoiceField(choices=('parties', 'documents', 'payments'), default='documents')
    payment_status = serializers.ChoiceField(choices=('all', 'unpaid', 'paid', 'unknown'), default='all')
    limit = serializers.IntegerField(min_value=1, max_value=50, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)

    def validate(self, values):
        if values.get('party_id') and values.get('unassigned_party'):
            raise serializers.ValidationError('往来单位与未指定单位筛选不能同时使用。')
        return values

    def validate_month(self, value):
        if not 1900 <= int(value[:4]) <= 9998:
            raise serializers.ValidationError('月份年份须在 1900 至 9998 之间。')
        return value


def _documents(query, kind):
    fields = ['id', 'number', '_party_id', '_party_name', '_country_name', 'due']
    if kind == 'domestic_freight':
        fields.append('_party_type')
    extra = {
        'purchase': ['creation_key', 'reference_number', 'order_date'],
        'shipment': ['shipment_date'], 'domestic_freight': ['shipment_date'],
        'batch': ['creation_key', 'notes', 'departed_at'],
        'inbound': ['confirmed_at', 'batch__creation_key', 'batch__notes', 'batch__arrived_warehouse_at'],
    }[kind]
    for data in query.values(*fields, *extra).iterator(chunk_size=500):
        obj = SimpleNamespace(**data)
        if kind == 'inbound':
            obj.batch = SimpleNamespace(**{k[7:]: v for k, v in data.items() if k.startswith('batch__')})
        yield {'id': data['id'], 'kind': kind, 'number': data['number'],
               'document_time': document_time(kind, obj), 'party_id': data['_party_id'], 'party_name': data['_party_name'],
               **({'party_type': data['_party_type']} if kind == 'domestic_freight' else {}),
               'country_name': data['_country_name'], 'due': data['due']}


def _period_totals(query, owner, start, end):
    signed = Case(When(reverses_id__isnull=False, then=-F('amount')), default=F('amount'), output_field=MONEY)
    rows = query.filter(date__lt=end).order_by().values(owner).annotate(
        before=Sum(Case(When(date__lt=start, then=signed), default=ZERO, output_field=MONEY)),
        current=Sum(Case(When(date__gte=start, then=signed), default=ZERO, output_field=MONEY)))
    return {row[owner]: (row['before'] or D0, row['current'] or D0) for row in rows}


def _party_row(party_id, name):
    return {'party_id': party_id, 'party_name': name or '未指定往来单位',
        'document_count': 0, 'unknown_documents': 0, 'undated_documents': 0,
        **{key: D0 for key in AMOUNTS}}


def _party_totals(document_rows):
    parties = {}
    for row in document_rows:
        key = (row['party_type'], row['party_id']) if 'party_type' in row else row['party_id']
        party = parties.setdefault(key, _party_row(row['party_id'], row['party_name']))
        if 'party_type' in row:
            party['party_type'] = row['party_type']
        for key in AMOUNTS:
            party[key] += row[key] or D0
        for key in ('unknown_documents', 'undated_documents'):
            party[key] += row[key]
        party['document_count'] += 1
    return parties


def _supplier_balances(parties, document_rows, docs, cash, historical, purchase_docs, purchase_cash, start, end):
    """Supplier-level cash includes PO deposits; applications are informational."""
    states = defaultdict(lambda: defaultdict(lambda: D0))
    for row in document_rows:
        obj = docs[row['id']]
        if row['unknown_reason']:
            continue
        day = date.fromisoformat(row['document_time'][:10]); state = states[row['party_id']]
        state['before_due'] += obj['due'] if day < start else D0
        state['new_due'] += obj['due'] if start <= day < end else D0
        before, current = cash.get(row['id'], (D0, D0))
        state['before_cash'] += before; state['current_cash'] += current
        history_day, amount = historical.get(row['id'], (None, D0))
        state['before_history'] += amount if history_day and history_day < start else D0
        state['current_history'] += amount if history_day and start <= history_day < end else D0
    for pk, (before, current) in purchase_cash.items():
        obj = purchase_docs[pk]; party_id = obj['party_id']
        party = parties.setdefault(party_id, _party_row(party_id, obj['party_name']))
        party['paid_amount'] += current
        states[party_id]['before_cash'] += before; states[party_id]['current_cash'] += current
    for party_id, party in parties.items():
        state = states[party_id]
        opening = state['before_due'] - state['before_cash'] - state['before_history']
        ending = opening + state['new_due'] - state['current_cash'] - state['current_history']
        party.update(opening_payable=max(opening, D0), opening_credit=max(-opening, D0),
            new_payable=state['new_due'], remaining_amount=max(ending, D0), credit_balance=max(-ending, D0))


def monthly_data(actor, values):
    month = values.get('month') or business_date().strftime('%Y-%m')
    year, month_number = map(int, month.split('-'))
    start = date(year, month_number, 1)
    end = date(year + (month_number == 12), 1 if month_number == 12 else month_number + 1, 1)
    queue = values['queue']; kind = KINDS[queue]; owner = OWNERS[queue]
    scoped = scope(actor, values.get('country_id'))
    query = _money_targets(queue, scoped)
    if values.get('party_id'):
        query = query.filter(_party_id=values['party_id'])
        if queue == 'domestic':
            query = query.filter(_party_type=values.get('party_type', 'carrier'))
    elif values.get('unassigned_party'):
        query = query.filter(_party_id__isnull=True)
    docs = {row['id']: row for row in _documents(query, kind)}
    # The owner subquery retains all document permissions, including country and party.
    payments = PaymentRecord.objects.filter(tenant_id=actor.tenant_id,
        **{owner + '__in': query.values('pk')}, purpose='domestic_freight' if queue == 'domestic' else 'goods')
    cash = _period_totals(payments, owner, start, end)
    display_payments = payments
    purchase_docs = {}; purchase_cash = {}; purchase_payments = PaymentRecord.objects.none()
    if queue == 'supplier':
        purchase_query = _money_targets('deposit', scoped)
        if values.get('party_id'):
            purchase_query = purchase_query.filter(_party_id=values['party_id'])
        elif values.get('unassigned_party'):
            purchase_query = purchase_query.filter(_party_id__isnull=True)
        purchase_docs = {row['id']: row for row in _documents(purchase_query, 'purchase')}
        purchase_payments = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, purpose='goods',
            purchase_order_id__in=purchase_query.values('pk'))
        purchase_cash = _period_totals(purchase_payments, 'purchase_order_id', start, end)
        display_payments = PaymentRecord.objects.filter(tenant_id=actor.tenant_id, purpose='goods').filter(
            Q(shipment_id__in=query.values('pk')) | Q(purchase_order_id__in=purchase_query.values('pk')))
    applied = {}
    if queue == 'supplier':
        applications = PaymentApplication.objects.filter(tenant_id=actor.tenant_id, shipment_id__in=query.values('pk'))
        applied = _period_totals(applications, 'shipment_id', start, end)
    historical = {}
    if queue in ('supplier', 'carrier'):
        records = SettlementRecord.objects.filter(tenant_id=actor.tenant_id,
            **{owner + '__in': query.values('pk')}, current_revision__isnull=False)
        historical = {r[owner]: (r['current_revision__date'], r['current_revision__recorded_amount'])
            for r in records.values(owner, 'current_revision__date', 'current_revision__recorded_amount')}
    months = {month, business_date().strftime('%Y-%m')}
    months.update(d.strftime('%Y-%m') for d in payments.values_list('date', flat=True).distinct())
    months.update(d.strftime('%Y-%m') for d in purchase_payments.values_list('date', flat=True).distinct())
    if queue == 'supplier':
        months.update(d.strftime('%Y-%m') for d in applications.values_list('date', flat=True).distinct())
    months.update(day.strftime('%Y-%m') for day, _ in historical.values() if day)
    months.update(r['document_time'][:7] for r in docs.values() if r['document_time'])
    summary = {key: D0 for key in AMOUNTS}
    summary.update(unknown_documents=0, undated_documents=0)
    document_rows = []
    for pk, obj in docs.items():
        day = date.fromisoformat(obj['document_time'][:10]) if obj['document_time'] else None
        before_cash, current_cash = cash.get(pk, (D0, D0))
        before_applied, current_applied = applied.get(pk, (D0, D0))
        historical_day, historical_amount = historical.get(pk, (None, D0))
        before_history = historical_amount if historical_day and historical_day < start else D0
        current_history = historical_amount if historical_day and start <= historical_day < end else D0
        if day and day >= end and not any((before_cash, current_cash, before_applied, current_applied, before_history, current_history)):
            continue
        row = {k: v for k, v in obj.items() if k != 'due'}
        row.update({key: D0 for key in AMOUNTS})
        row.update(paid_amount=current_cash, applied_amount=current_applied, historical_paid_amount=current_history)
        row['_paid_by_month_end'] = before_cash + current_cash + before_applied + current_applied + before_history + current_history
        summary['paid_amount'] += current_cash
        summary['applied_amount'] += current_applied
        summary['historical_paid_amount'] += current_history
        reasons = []
        if day is None:
            summary['undated_documents'] += 1; reasons.append('缺少单据业务日期')
        if obj['due'] is None:
            summary['unknown_documents'] += 1; reasons.append('应付金额未确认')
        row['unknown_reason'] = '；'.join(reasons)
        row.update(unknown_documents=int(obj['due'] is None), undated_documents=int(day is None))
        if reasons:
            for key in ('opening_payable', 'new_payable', 'remaining_amount', 'opening_credit', 'credit_balance'):
                row[key] = None
            summary['unknown_payment_amount'] += current_cash
            row['unknown_payment_amount'] = current_cash
        else:
            opening = (obj['due'] if day < start else D0) - before_cash - before_applied - before_history
            addition = obj['due'] if start <= day < end else D0
            ending = opening + addition - current_cash - current_applied - current_history
            row.update(opening_payable=max(opening, D0), opening_credit=max(-opening, D0),
                       new_payable=addition, remaining_amount=max(ending, D0), credit_balance=max(-ending, D0))
            for key in ('opening_payable', 'opening_credit', 'new_payable', 'remaining_amount', 'credit_balance'):
                summary[key] += row[key]
        document_rows.append(row)
    document_status_counts = {'all': len(document_rows), 'unpaid': 0, 'paid': 0, 'unknown': 0}
    for row in document_rows:
        if row['remaining_amount'] is None:
            row['payment_status'] = 'unknown'
        elif row['remaining_amount'] == D0:
            row['payment_status'] = 'paid'
        elif row['_paid_by_month_end'] > D0:
            row['payment_status'] = 'partial'
        else:
            row['payment_status'] = 'unpaid'
        if row['payment_status'] in ('unpaid', 'partial'):
            document_status_counts['unpaid'] += 1
        else:
            document_status_counts[row['payment_status']] += 1
        row.pop('_paid_by_month_end')
    document_rows.sort(key=lambda r: (r['document_time'] or '', r['id']), reverse=True)
    parties = _party_totals(document_rows)
    if queue == 'supplier':
        _supplier_balances(parties, document_rows, docs, cash, historical, purchase_docs, purchase_cash, start, end)
        summary = {key: sum((p[key] for p in parties.values()), D0) for key in AMOUNTS}
        summary.update({key: sum(p[key] for p in parties.values()) for key in ('unknown_documents', 'undated_documents')})
    offset, limit = values['offset'], values['limit']
    filtered_documents = document_rows
    status_filter = values.get('payment_status', 'all')
    if values['view'] == 'documents' and status_filter != 'all':
        if status_filter == 'unpaid':
            filtered_documents = [r for r in document_rows if r['payment_status'] in ('unpaid', 'partial')]
        else:
            filtered_documents = [r for r in document_rows if r['payment_status'] == status_filter]
    rows = filtered_documents[offset:offset + limit]; count = len(filtered_documents)
    if values['view'] == 'parties':
        ordered = sorted(parties.values(), key=lambda p: (-p['remaining_amount'], p['party_name'], p['party_id'] or 0))
        count = len(ordered)
        rows = ordered[offset:offset + limit]
    if values['view'] == 'payments':
        monthly_payments = display_payments.filter(date__gte=start, date__lt=end)
        count = monthly_payments.count()
        page = list(monthly_payments.select_related('reverses').order_by('-date', '-pk')[offset:offset + limit])
        voucher_ids = [p.reverses_id or p.pk for p in page]
        vouchers = defaultdict(list)
        for v in PaymentVoucher.objects.filter(tenant_id=actor.tenant_id, payment_id__in=voucher_ids).order_by('pk').values(
                'id', 'payment_id', 'file_name', 'media_type', 'byte_size'):
            vouchers[v['payment_id']].append({'id': v['id'], 'file_name': v['file_name'],
                'content_type': v['media_type'], 'byte_size': v['byte_size']})
        reversed_ids = set(display_payments.filter(reverses_id__in=[p.pk for p in page]).values_list('reverses_id', flat=True))
        rows = []
        for payment in page:
            payment_kind = kind
            if queue == 'supplier' and payment.purchase_order_id:
                source_id = payment.purchase_order_id; obj = purchase_docs[source_id]; payment_kind = 'purchase'
            else:
                source_id = getattr(payment, owner); obj = docs[source_id]
            proof_id = payment.reverses_id or payment.pk
            rows.append({'id': payment.pk, 'kind': payment_kind, 'source_id': source_id, 'number': obj['number'],
                'party_name': obj['party_name'], 'date': payment.date.isoformat(),
                'amount': str(-payment.amount if payment.reverses_id else payment.amount),
                'reference_number': payment.reference_number, 'is_reversal': bool(payment.reverses_id),
                'reversed': payment.pk in reversed_ids, 'voucher_payment_id': proof_id,
                'vouchers': vouchers[proof_id], 'notes': payment.notes,
                'date_inferred': payment.account_snapshot.get('date_confirmed_from_voucher') is False})
    else:
        rows = [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in rows]
    return {'month': month, 'queue': queue, 'summary': {k: str(v) if isinstance(v, Decimal) else v for k, v in summary.items()},
        'document_status_counts': document_status_counts,
        'rows': rows, 'count': count, 'available_months': sorted(months, reverse=True),
        'notices': ['按当前确认应付金额及单据业务日期回溯，不是已锁定的历史月结快照；未作汇率换算。',
            '月期初、月末应付与预付/超付分列；本月新增应付、实际付款、定金抵扣及历史已付登记分别列示。',
            '付款按付款业务日期归月，冲销按冲销业务日期负数计入。供应商付款含采购定金和发货单直接付款，抵扣不重复作为现金付款；采购定金页为同笔资金视角，不相加。',
            '供应商对象余额按发货金额扣除累计现金付款及历史已付；单据余额按实际付款与抵扣归属显示。',
            '缺日期或未确认应付单据不计入已知余额，其本月付款仍列入付款额并单列待核对付款；各业务类型不相加。']}


class MonthlyPayables(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        query = MonthlyQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response({'data': monthly_data(request.user, query.validated_data)})
