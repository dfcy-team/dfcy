"""Scoped monthly reconstruction from current obligations and dated cash events."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Case, F, Q, Sum, When
from rest_framework import serializers
from rest_framework.response import Response
from django.http import HttpResponse

from .dashboard import MONEY, ZERO, _money_targets, scope
from .dates import business_date
from .document_time import document_time
from .models import PaymentApplication, PaymentRecord, PaymentVoucher, SettlementRecord
from .cost_models import PaymentClassification, PaymentPlanRecord, PaymentCurrencyConfirmation
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
    plan_current = defaultdict(lambda: {'corporate': D0, 'personal': D0, 'unknown': D0})
    plan_rows = []
    plan_query = PaymentPlanRecord.objects.filter(tenant_id=actor.tenant_id, kind=kind,
        **({'shipment__in': query.values('pk')} if queue in ('supplier','domestic') else
           {'batch__in': query.values('pk')} if queue=='carrier' else {})) if queue in ('supplier','domestic','carrier') else PaymentPlanRecord.objects.none()
    from .monthly_nature_balances import matches_party, monthly_currency
    from .payment_plan_links import line_balances
    from .payment_request_models import SupplyPaymentRequest
    plans = list(plan_query.only('tenant_id','currency','lines','party_snapshot','shipment_id','batch_id'))
    month_plan_ids = [plan.pk for plan in plans if any(
        line.get('due_date') and start.isoformat() <= line['due_date'] < end.isoformat()
        for line in plan.lines or [])]
    linked_by_plan = defaultdict(list)
    if month_plan_ids:
        for linked in SupplyPaymentRequest.objects.filter(tenant_id=actor.tenant_id, plan_id__in=month_plan_ids).select_related(
                'payment','approval','batch__approval').prefetch_related('payment__reversal'):
            linked_by_plan[linked.plan_id].append(linked)
    plan_balance_cache = {}
    for plan in plans:
        plan_doc = docs.get(getattr(plan,owner))
        if not plan_doc or not matches_party(plan.party_snapshot,plan_doc,'supplier' if kind=='shipment' else 'carrier'):
            continue
        if plan.pk not in month_plan_ids:
            continue
        balances = line_balances(plan, linked_requests=linked_by_plan[plan.pk])
        plan_balance_cache[plan.pk] = balances
        for index, line in enumerate(plan.lines or []):
            balance = balances[str(line.get('line_id') or f'legacy-{plan.pk}-{index}')]
            if line.get('due_date') and start.isoformat() <= line['due_date'] < end.isoformat():
                nature=line.get('nature') if line.get('nature') in ('corporate','personal') else 'unknown'
                currency = monthly_currency(kind, plan.currency)
                amount = balance['remaining_amount']
                plan_current[currency][nature] += amount
                plan_rows.append({'party_name':(plan.party_snapshot or {}).get('name') or '未指定往来单位',
                    'currency':currency,'nature':nature,'due_date':line['due_date'],'amount':str(amount),
                    'kind':kind,'source_id':plan_doc['id'],'number':plan_doc['number'],
                    'original_amount':str(line.get('amount','0')),'paid_amount':str(balance['paid_amount']),
                    'reserved_amount':str(balance['reserved_amount']),'available_amount':str(balance['available_amount']),
                    'label':line.get('note') or line.get('label') or line.get('name') or ''})
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
    # Nature cash is actual dated cash only. Unknown stays separate; reversal
    # follows the original payment's saved classification.
    cash_nature = defaultdict(lambda: {'corporate': D0, 'personal': D0, 'unknown': D0})
    payment_rows = list(display_payments.filter(date__gte=start, date__lt=end).select_related('reverses'))
    ids = {p.pk for p in payment_rows} | {p.reverses_id for p in payment_rows if p.reverses_id}
    classifications = {x.payment_id: x.allocations for x in PaymentClassification.objects.filter(
        tenant_id=actor.tenant_id, payment_id__in=ids)}
    confirmed_currencies={r.payment_id:r.currency for r in PaymentCurrencyConfirmation.objects.filter(tenant_id=actor.tenant_id,payment_id__in=ids)}
    for payment in payment_rows:
        source_id = payment.reverses_id or payment.pk
        original = payment.reverses if payment.reverses_id else payment
        snapshot = (original.account_snapshot if original else payment.account_snapshot) or {}
        allocations = classifications.get(source_id) or []
        nature = snapshot.get('nature')
        signed = -payment.amount if payment.reverses_id else payment.amount
        currency = monthly_currency(kind, snapshot.get('currency'), confirmed_currencies.get(source_id))
        if nature in ('corporate','personal'):
            cash_nature[currency][nature] += signed
        elif allocations:
            total = sum((Decimal(str(a.get('amount','0'))) for a in allocations), D0)
            if total == (original.amount if original else payment.amount):
                for a in allocations:
                    if a.get('nature') in ('corporate','personal'):
                        cash_nature[currency][a['nature']] += signed * Decimal(str(a['amount'])) / total
                    else: cash_nature[currency]['unknown'] += signed * Decimal(str(a.get('amount','0'))) / total
            else: cash_nature[currency]['unknown'] += signed
        else: cash_nature[currency]['unknown'] += signed
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
            payment_snapshot = ((payment.reverses if payment.reverses_id else payment).account_snapshot or {})
            classification = classifications.get(proof_id) or []
            payment_nature = payment_snapshot.get('nature')
            if payment_nature not in ('corporate', 'personal'):
                classified_natures = {x.get('nature') for x in classification}
                payment_nature = (next(iter(classified_natures)) if len(classified_natures) == 1 else
                                  'mixed' if classified_natures else 'unknown')
            rows.append({'id': payment.pk, 'kind': payment_kind, 'source_id': source_id, 'number': obj['number'],
                'party_name': obj['party_name'], 'date': payment.date.isoformat(),
                'amount': str(-payment.amount if payment.reverses_id else payment.amount),
                'nature': payment_nature, 'currency': monthly_currency(kind, payment_snapshot.get('currency'), confirmed_currencies.get(proof_id)),
                'reference_number': payment.reference_number, 'is_reversal': bool(payment.reverses_id),
                'reversed': payment.pk in reversed_ids, 'voucher_payment_id': proof_id,
                'vouchers': vouchers[proof_id], 'notes': payment.notes,
                'date_inferred': payment.account_snapshot.get('date_confirmed_from_voucher') is False})
    else:
        rows = [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in rows]
    from .monthly_nature_balances import nature_balances
    summary['nature_balances'] = nature_balances(actor, kind, query, docs, display_payments, purchase_docs, start, end, plan_balance_cache=plan_balance_cache)
    summary['paid_nature_by_currency'] = [
        {'currency': currency, **{key: str(value) for key, value in nature.items()}}
        for currency, nature in sorted(cash_nature.items())]
    summary['current_plan_by_currency'] = [
        {'currency': currency, **{key: str(value) for key, value in nature.items()}}
        for currency, nature in sorted(plan_current.items())]
    return {'month': month, 'queue': queue, 'summary': {k: str(v) if isinstance(v, Decimal) else v for k, v in summary.items()},
        'document_status_counts': document_status_counts,
        'rows': rows, 'count': count, 'available_months': sorted(months, reverse=True),
        'current_plan_rows': plan_rows,
        'notices': ['按当前确认应付金额及单据业务日期回溯，不是已锁定的历史月结快照；未作汇率换算。',
            '月期初、月末应付与预付/超付分列；本月新增应付、实际付款、定金抵扣及历史已付登记分别列示。',
            '付款按付款业务日期归月，冲销按冲销业务日期负数计入。供应商付款含采购定金和发货单直接付款，抵扣不重复作为现金付款；采购定金页为同笔资金视角，不相加。',
            '供应商对象余额按发货金额扣除累计现金付款及历史已付；单据余额按实际付款与抵扣归属显示。',
            '对公/对私现金仅按付款账户快照或已审核的分类记录汇总；供应商货款和国内运费缺少币种时按人民币（CNY）展示，其他款项保留“币种未记录”；不同币种分行展示。当前付款计划按计划到期日及币种统计，扣除已关联申请的净付款；审批占用仍属于待付款，冲销恢复余额。未关联的历史或直接付款不自动核销计划，需人工核对。计划不是历史冻结快照。',
            '分类余额按当前确认的应付性质回溯，非历史冻结值；付款性质或币种缺失时单列待核对，不跨性质或币种抵扣。分类付款超出应付不代表可退款。有未分类或币种缺失项目时，月末应付不提供确定值，参考应付仅供核对。',
            '缺日期或未确认应付单据不计入已知余额，其本月付款仍列入付款额并单列待核对付款；各业务类型不相加。']}


class MonthlyPayables(InternalAPI):
    http_method_names = ['get', 'head', 'options']

    def get(self, request):
        query = MonthlyQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = monthly_data(request.user, query.validated_data)
        if request.query_params.get('export') == 'xlsx':
            from io import BytesIO
            from openpyxl import Workbook
            wb=Workbook(); ws=wb.active; ws.title='月度汇总'
            summary=data['summary']; ws.append(['月份','往来类别','币种','款项性质','金额类别','金额'])
            # Keep unlike currencies and cash versus current plan on separate rows.
            for row in summary.get('paid_nature_by_currency', []):
                for nature in ('corporate','personal','unknown'):
                    ws.append([data['month'],data['queue'],row['currency'],{'corporate':'对公/正报','personal':'对私','unknown':'性质待确认'}[nature],'本月实际付款',row[nature]])
            for row in summary.get('current_plan_by_currency', []):
                for nature in ('corporate','personal','unknown'):
                    ws.append([data['month'],data['queue'],row['currency'],{'corporate':'对公/正报','personal':'对私','unknown':'性质待确认'}[nature],'本月当前计划',row[nature]])
            ws.append([data['month'],data['queue'],'币种未统一记录','来源未拆分','期初应付',summary.get('opening_payable')])
            ws.append([data['month'],data['queue'],'币种未统一记录','来源未拆分','本月新增应付',summary.get('new_payable')])
            ws.append([data['month'],data['queue'],'币种未统一记录','来源未拆分','剩余应付',summary.get('remaining_amount')])
            parties=wb.create_sheet('往来单位月度明细'); parties.append(['往来单位','币种','性质分类','期初应付','本月新增应付','本月付款','剩余应付','本月计划'])
            offset=0
            while True:
                page=monthly_data(request.user,{**query.validated_data,'view':'parties','limit':50,'offset':offset})
                if not page['rows']: break
                for row in page['rows']:
                    parties.append([row['party_name'],'币种未统一记录','应付性质来源未拆分',row.get('opening_payable'),row.get('new_payable'),row.get('paid_amount'),row.get('remaining_amount'),'请查看计划明细'])
                offset += len(page['rows'])
                if offset >= page['count']: break
            payments=wb.create_sheet('本月付款明细'); payments.append(['付款日期','单据号','往来单位','币种','付款性质','本次金额','付款参考号','是否冲销'])
            offset=0
            while True:
                page=monthly_data(request.user,{**query.validated_data,'view':'payments','limit':50,'offset':offset})
                if not page['rows']: break
                for row in page['rows']:
                    payments.append([row['date'],row['number'],row['party_name'],row['currency'],{'corporate':'对公/正报','personal':'对私','mixed':'对公对私混合','unknown':'性质待确认'}.get(row['nature'],'性质待确认'),row['amount'],row['reference_number'], '是' if row['is_reversal'] else '否'])
                offset += len(page['rows'])
                if offset >= page['count']: break
            classified=wb.create_sheet('往来单位性质对账')
            classified.append(['往来单位','币种','性质','期初应付','期初分类付款超额','本月新增应付','本月付款','本月历史已付登记','月末应付（待核对时不提供）','月末参考应付（未核实）','月末分类付款超额（待核对时不提供）','参考分类付款超额（未核实）','本月当前计划','核对状态','未记录币种的来源'])
            for row in summary.get('nature_balances',[]):
                classified.append([row['party_name'],row['currency'],{'corporate':'对公/正报','personal':'对私','unknown':'性质待确认'}[row['nature']],
                    row['opening_payable'],row['opening_credit'],row['new_payable'],row['paid_amount'],row['historical_paid_amount'],
                    row['remaining_amount'],row['reference_remaining_amount'],row['credit_balance'],row['reference_credit_balance'],row['current_plan_amount'],'待核对' if row['needs_review'] else '已分类',row['source_number']])
            plans=wb.create_sheet('本月当前付款计划'); plans.append(['计划到期日','往来单位','币种','付款性质','剩余计划金额','款项名称','原计划金额','已核销金额','审批占用金额','可申请金额'])
            for row in data.get('current_plan_rows',[]):
                plans.append([row['due_date'],row['party_name'],row['currency'],{'corporate':'对公/正报','personal':'对私','unknown':'性质待确认'}[row['nature']],row['amount'],row['label'],row['original_amount'],row['paid_amount'],row['reserved_amount'],row['available_amount']])
            ws2=wb.create_sheet('口径说明')
            for line in data['notices']: ws2.append([line])
            ws2.append(['本月实际付款按付款账户快照或已审核的性质分类；历史冲销继承原付款分类。'] )
            ws2.append(['原总览保留未拆分口径；新增“往来单位性质对账”按当前确认来源分类回溯。未确认或失效的应付分类及缺失付款币种单列待核对，不按比例推算。'])
            ws2.append(['本月计划根据当前维护的到期月份查询，不是历史冻结计划；只有计划记录标明的币种参与按币种分行。'])
            for sheet in wb.worksheets:
                sheet.freeze_panes = 'A2'
                for cells in sheet.iter_rows():
                    for cell in cells:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
            stream=BytesIO();wb.save(stream); response=HttpResponse(stream.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');response['Content-Disposition']=f'attachment; filename="monthly-{data["queue"]}-{data["month"]}.xlsx"';return response
        return Response({'data': data})
