"""Domestic legacy and itemized payables, kept as separate financial owners."""
from decimal import Decimal, localcontext

from django.db.models import Q, Sum, F

from .document_time import document_time
from .settlement_table_query import MONEY_FIELDS
from .domestic_currency_totals import aggregate_money, currency_unit, serialise_money, guard_posting_units

ZERO = Decimal('0')


def _legacy_units(actor, rows):
    """Batch the same payment evidence used by the canonical currency resolver."""
    from types import SimpleNamespace
    from .cost_models import PaymentPlanRecord, PayableClassificationRecord, FeeRecord
    from .payment_plans import _source_currency
    codes = {}
    for row in rows:
        source = _source_currency('domestic_freight', SimpleNamespace(domestic_terms_snapshot=row['domestic_terms_snapshot']))
        codes[row['pk']] = {source} if source else set()
    if not codes:
        return {}
    for model in (PaymentPlanRecord, PayableClassificationRecord):
        for shipment_id, unit in model.objects.filter(tenant_id=actor.tenant_id,
                kind='domestic_freight', shipment_id__in=codes).values_list('shipment_id', 'currency'):
            if unit:
                codes[shipment_id].add(unit)
    for record in FeeRecord.objects.filter(tenant_id=actor.tenant_id, shipment_id__in=codes).select_related('current_revision'):
        revision = record.current_revision
        unit = (revision.cost_exchange or {}).get('currency') if revision else None
        if unit:
            codes[record.shipment_id].add(unit)
    return {pk: currency_unit(units) for pk, units in codes.items()}


def project(actor, scoped, legacy):
    from . import costs
    from .cost_models import PaymentRecord, PaymentCurrencyConfirmation
    from .domestic_expense_models import DomesticExpenseGroup

    # Use the same accessible shipment scope, not all tenant fee groups. A group
    # has its own payee even when shipment transport defaults subsequently change.
    groups = list(DomesticExpenseGroup.objects.filter(
        tenant_id=actor.tenant_id, is_active=True, shipment__in=scoped[3],
    ).select_related('shipment__order__country', 'supplier', 'carrier'))
    ids = [g.pk for g in groups]
    payments = PaymentRecord.objects.filter(
        tenant_id=actor.tenant_id, domestic_expense_group_id__in=ids,
        domestic_expense_group__shipment_id=F('shipment_id'), purpose='domestic_freight',
    )
    effective = Q(reverses__isnull=True, reversal__isnull=True)
    totals = {r['domestic_expense_group_id']: r for r in payments.order_by().values(
        'domestic_expense_group_id').annotate(
        paid=Sum('amount', filter=effective),
        corporate=Sum('amount', filter=effective & Q(account_snapshot__nature='corporate')),
        personal=Sum('amount', filter=effective & Q(account_snapshot__nature='personal')),
    )}
    fields = ['pk', 'number', '_party_type', '_party_id', '_party_name', 'due',
              'opening_amount', 'paid_amount', 'applied_amount', 'corporate_paid',
              'personal_paid', 'has_payment_history', '_review_has_request',
              'order__country__country_code', 'order__country__name', 'shipment_date', 'domestic_terms_snapshot']
    rows = []
    grouped_shipments = {g.shipment_id for g in groups}
    legacy_rows = list(legacy.order_by().values(*fields))
    legacy_units = _legacy_units(actor, legacy_rows)
    for item in legacy_rows:
        # A corrected zero legacy balance should not create a duplicate empty
        # row alongside the real itemized payable. Keep any payment/request audit.
        if (item['pk'] in grouped_shipments and item['due'] == ZERO
                and item['paid_amount'] == ZERO and not item['has_payment_history']
                and not item['_review_has_request']):
            continue
        kind = 'domestic_freight' if item['_party_id'] else 'shipment'
        date = item['shipment_date']
        rows.append(dict(
            id=item['pk'], number=item['number'], kind=kind, queue='domestic',
            href=f'/supply-chain/costs?kind={kind}&id={item["pk"]}',
            party_type=item['_party_type'], party_id=item['_party_id'],
            party_name=item['_party_name'] or '未选择国内承运商', currency=legacy_units[item['pk']],
            country_code=item['order__country__country_code'],
            country_name=item['order__country__name'],
            document_time=date.isoformat() if date else None,
            due_amount=item['due'], opening_amount=item['opening_amount'],
            paid_amount=item['paid_amount'], applied_amount=item['applied_amount'],
            corporate_paid=item['corporate_paid'], personal_paid=item['personal_paid'],
            has_payment_history=item['has_payment_history'], fee_items=[],
        ))
    for group in groups:
        amounts = totals.get(group.pk, {})
        party = group.supplier or group.carrier
        country = group.shipment.order.country
        rows.append(dict(
            id=group.pk, number=group.shipment.number, kind='domestic_expense',
            queue='domestic', href=f'/supply-chain/costs?kind=domestic_expense&id={group.pk}',
            party_type='supplier' if group.supplier_id else 'carrier',
            party_id=party.pk, party_name=party.name, currency=group.currency,
            country_code=country.country_code, country_name=country.name,
            document_time=document_time('domestic_freight', group.shipment),
            due_amount=costs.settlement_amount('domestic_expense', group), opening_amount=ZERO,
            paid_amount=amounts.get('paid') or ZERO, applied_amount=ZERO,
            corporate_paid=amounts.get('corporate') or ZERO,
            personal_paid=amounts.get('personal') or ZERO,
            has_payment_history=group.pk in totals, fee_items=[],
        ))
    owner_ids = {item['pk'] for item in legacy_rows} | {g.shipment_id for g in groups}
    posting_rows = PaymentRecord.objects.filter(
        Q(domestic_expense_group_id__in=ids, domestic_expense_group__shipment_id=F('shipment_id')) | Q(domestic_expense_group__isnull=True),
        tenant_id=actor.tenant_id, shipment_id__in=owner_ids, purpose='domestic_freight',
        reverses__isnull=True, reversal__isnull=True).exclude(amount=ZERO).values(
            'pk', 'shipment_id', 'domestic_expense_group_id', 'amount', 'account_snapshot__currency', 'account_snapshot__nature')
    posting_rows = list(posting_rows)
    missing_ids = [p['pk'] for p in posting_rows if p['account_snapshot__currency'] in (None, '')]
    confirmations = dict(PaymentCurrencyConfirmation.objects.filter(tenant_id=actor.tenant_id,
        payment_id__in=missing_ids).values_list('payment_id', 'currency')) if missing_ids else {}
    posting_units = {}
    for item in posting_rows:
        key = ('group', item['domestic_expense_group_id']) if item['domestic_expense_group_id'] else ('legacy', item['shipment_id'])
        raw_unit = item['account_snapshot__currency']
        if raw_unit in (None, ''):
            raw_unit = confirmations.get(item['pk'])
            source = 'legacy_confirmation' if raw_unit else 'unknown'
        else:
            source = 'posting_snapshot'
        unit = currency_unit({raw_unit}) if isinstance(raw_unit, str) else None
        posting_units.setdefault(key, []).append(dict(amount=item['amount'], currency=unit,
            nature=item['account_snapshot__nature'], unit_source=source))
    for row in rows:
        owner = ('group' if row['kind'] == 'domestic_expense' else 'legacy', row['id'])
        guard_posting_units(row, posting_units.get(owner, []))
        due, paid = row['due_amount'], row['paid_amount']
        row.update(remaining_amount=None if due is None or paid is None else max(due - paid, ZERO),
                   unsettled=None if due is None or paid is None else max(due - paid, ZERO),
                   over_recorded=None if paid is None else ZERO if due is None else max(paid - due, ZERO),
                   available_prepayment=ZERO,
                   unknown_paid=None if paid is None else paid - row['corporate_paid'] - row['personal_paid'])
    return rows


def table(rows, values, payment_matches=None):
    def contains(value, search):
        return str(search).casefold() in str(value or '').casefold()

    def matches(row):
        if values.get('party_id') and (row['party_id'] != values['party_id']
                or row['party_type'] != values.get('party_type', 'carrier')):
            return False
        if values.get('search') and not any(contains(row[f], values['search']) for f in ('number', 'party_name')):
            return False
        for key, field in [('column_number', 'number'), ('column_country', 'country_name'), ('column_party', 'party_name')]:
            if values.get(key) and not contains(row[field], values[key]):
                return False
        if payment_matches is not None and (row['kind'], row['id']) not in payment_matches:
            return False
        status = values.get('status', 'all')
        if status == 'pending' and not (row['due_amount'] is None or row['remaining_amount'] > 0 or row['over_recorded'] > 0):
            return False
        if status == 'settled' and not (row['due_amount'] is not None and row['remaining_amount'] == 0 and row['over_recorded'] == 0):
            return False
        natures = set(row.get('payment_natures', [])) if row.get('monetary_currency_conflict') else set()
        nature = values.get('payment_nature')
        if nature == 'mixed' and not ({'corporate', 'personal'} <= natures or ((row['corporate_paid'] or ZERO) > 0 and (row['personal_paid'] or ZERO) > 0)):
            return False
        if nature in ('corporate', 'personal') and nature not in natures and (row[nature + '_paid'] or ZERO) <= 0:
            return False
        if nature == 'unknown' and not ('unknown' in natures or (row['unknown_paid'] or ZERO) > 0 or row['paid_amount'] == 0):
            return False
        for field in MONEY_FIELDS:
            for suffix in ('min', 'max'):
                bound = values.get(field + '_' + suffix)
                if bound is not None and (row[field] is None or
                        (row[field] < bound if suffix == 'min' else row[field] > bound)):
                    return False
        date = row['document_time']
        return all(not values.get(key) or date and compare(date[:10], str(values[key])) for key, compare in (
            ('document_from', lambda a, b: a >= b), ('document_to', lambda a, b: a <= b)))

    rows = [row for row in rows if matches(row)]
    key, descending = values.get('sort_by'), values.get('sort_order') == 'descending'
    identity = lambda row: (row['id'], row['kind'])
    if key:
        known = sorted((r for r in rows if r.get(key) is not None and r.get(key) != ''),
                       key=identity, reverse=bool(key == 'document_time' and descending))
        known.sort(key=lambda row: ((row.get('currency') or ''), row[key]) if key in MONEY_FIELDS else row[key], reverse=descending)
        rows = known + sorted((r for r in rows if r.get(key) is None or r.get(key) == ''), key=identity)
    else:
        rows.sort(key=identity, reverse=True)
    summary = {'documents': len(rows), 'unknown_documents': sum(r['due_amount'] is None for r in rows)}
    summary.update(serialise_money(aggregate_money(rows, (*MONEY_FIELDS, 'available_prepayment', 'corporate_paid', 'personal_paid', 'unknown_paid'))))
    start = values.get('offset', 0)
    page = rows[start:start + values.get('limit', 20)]
    return {'data': [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in page],
            'count': len(rows), 'limit': values.get('limit', 20), 'offset': start, 'summary': summary}


def queue(actor, scoped, legacy, values):
    from rest_framework.exceptions import ValidationError
    from .cost_models import PaymentRecord
    if values.get('item_status'):
        raise ValidationError({'item_status': '费用项目状态仅用于批次货运费及入库清关费用。'})
    payment_matches = None
    if values.get('payment_item'):
        payments = PaymentRecord.objects.filter(
            Q(domestic_expense_group__isnull=True) | Q(domestic_expense_group__shipment_id=F('shipment_id')),
            tenant_id=actor.tenant_id, shipment__in=scoped[3], purpose='domestic_freight',
            reverses__isnull=True, reversal__isnull=True,
            item_snapshot__name__icontains=values['payment_item'],
        ).values_list('shipment_id', 'domestic_expense_group_id')
        payment_matches = set()
        for shipment, group in payments:
            if group:
                payment_matches.add(('domestic_expense', group))
            else:
                payment_matches.update({('domestic_freight', shipment), ('shipment', shipment)})
    return table(project(actor, scoped, legacy), values, payment_matches)


ROLLUP_FIELDS = ('amount', 'opening', 'paid', 'converted', 'applied', 'recorded', 'unsettled',
                 'over_recorded', 'available_prepayment', 'known_direct_paid', 'known_opening')
CARD_FIELDS = ('amount', 'opening', 'paid', 'applied', 'recorded', 'unsettled',
               'over_recorded', 'available_prepayment', 'cash_paid_amount')


def rollup(actor, scoped, legacy):
    grouped = {}
    for item in project(actor, scoped, legacy):
        key = item['party_type'], item['party_id'], item['party_name'], item['currency']
        grouped.setdefault(key, []).append(item)
    rows = []
    for key, items in grouped.items():
        monetary = []
        for item in items:
            monetary.append(dict(currency=item['currency'], unresolved_currency_nonzero=item.get('unresolved_currency_nonzero', False), amount=item['due_amount'],
                opening=item['opening_amount'], paid=item['paid_amount'], converted=ZERO,
                applied=item['applied_amount'], recorded=item['paid_amount'], unsettled=item['remaining_amount'],
                over_recorded=item['over_recorded'], available_prepayment=ZERO,
                known_direct_paid=ZERO, known_opening=ZERO))
        row = aggregate_money(monetary, ROLLUP_FIELDS)
        row.update(_party_type=key[0], _party_id=key[1], _party_name=key[2],
                   documents=len(items), unknown_documents=sum(item['due_amount'] is None for item in items))
        row['cash_paid_amount'] = (row['paid'] - row['opening'] - row['converted']
                                  if all(row[k] is not None for k in ('paid', 'opening', 'converted')) else None)
        rows.append(row)
    # Ordering is within each original unit, never a comparison of CNY and PHP numbers.
    return sorted(rows, key=lambda row: (row['currency'] or '', row['unsettled'] is None,
        -(row['unsettled'] or ZERO), row['_party_id'] is not None, row['_party_id'] or 0,
        row['_party_type'], row['_party_name'] or ''))


def dashboard_data(rows):
    result = aggregate_money(rows, CARD_FIELDS)
    result.update(documents=sum(r['documents'] for r in rows),
                  unknown_documents=sum(r['unknown_documents'] for r in rows))
    result['available'] = result['available_prepayment']
    result['ranking'] = [dict(party_type=r['_party_type'], party_id=r['_party_id'], id=r['_party_id'],
        name=r['_party_name'], currency=r['currency'], unknown_documents=r['unknown_documents'],
        **{k: r[k] for k in CARD_FIELDS}) for r in rows[:10]]
    return serialise_money(result)
