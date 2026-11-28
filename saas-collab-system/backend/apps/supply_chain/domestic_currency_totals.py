"""Domestic reconciliation keeps original monetary units; it never invents FX."""
from decimal import Decimal, localcontext

ZERO = Decimal('0')


def currency_unit(codes, exchange=None):
    codes = set(codes)
    if (exchange or {}).get('currency'):
        codes.add(exchange['currency'])
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    return code if isinstance(code, str) and len(code) == 3 and code.isascii() and code.isalpha() and code.isupper() else None


def aggregate_money(rows, fields):
    rows, fields = list(rows), tuple(fields)
    buckets = {}
    for row in rows:
        unit = currency_unit({row.get('currency')})
        buckets.setdefault(unit, []).append(row)
    unknown_nonzero = any(r.get('unresolved_currency_nonzero') for r in rows) or any(r.get(f) not in (None, ZERO) for r in buckets.get(None, []) for f in fields)
    known = {unit for unit in buckets if unit is not None}
    incompatible = len(known) > 1 or unknown_nonzero

    def totals(items, unknown=False):
        with localcontext() as ctx:
            ctx.prec = 60
            return {f: (None if (unknown and any(r.get(f) not in (None, ZERO) for r in items)) or
                        (items and all(r.get(f) is None for r in items)) else
                        sum((r.get(f) or ZERO for r in items), ZERO)) for f in fields}

    result = {f: None for f in fields} if incompatible else totals(rows)
    result.update(currency=next(iter(known)) if len(known) == 1 and not unknown_nonzero else None,
                  mixed_currency=len(known) > 1, unresolved_currency_nonzero=unknown_nonzero,
                  unknown_currency_documents=sum(r.get('unknown_currency_documents', 1) for r in buckets.get(None, [])),
                  totals_by_currency={unit or 'UNKNOWN': totals(items, unit is None) for unit, items in buckets.items()})
    return result


def serialise_money(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: serialise_money(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialise_money(v) for v in value]
    return value


def guard_posting_units(row, postings):
    """A source currency cannot relabel immutable cash posted in another unit."""
    postings = [p for p in postings if p['amount'] != ZERO]
    facts = [dict(currency=p['currency'], paid_amount=p['amount'],
                  corporate_paid=p['amount'] if p['nature'] == 'corporate' else ZERO,
                  personal_paid=p['amount'] if p['nature'] == 'personal' else ZERO,
                  unknown_paid=p['amount'] if p['nature'] not in ('corporate', 'personal') else ZERO) for p in postings]
    row['payment_totals_by_currency'] = serialise_money(aggregate_money(facts,
        ('paid_amount', 'corporate_paid', 'personal_paid', 'unknown_paid'))['totals_by_currency'])
    row['payment_currency_evidence_sources'] = sorted({p.get('unit_source', 'posting_snapshot') for p in postings})
    row['payment_natures'] = sorted({p['nature'] if p['nature'] in ('corporate', 'personal') else 'unknown' for p in postings})
    units = {currency_unit({p['currency']}) for p in postings}
    due_unit = currency_unit({row.get('currency')})
    conflict = bool(postings) and (due_unit is None or units != {due_unit})
    conflict = conflict or (row.get('paid_amount') not in (None, ZERO) and not postings)
    if conflict:
        row['original_due'] = {'currency': due_unit, 'amount': serialise_money(row['due_amount'])}
        row['currency'] = None
        row['monetary_currency_conflict'] = True
        row['unresolved_currency_nonzero'] = True
        for field in ('due_amount', 'opening_amount', 'paid_amount', 'applied_amount', 'corporate_paid', 'personal_paid'):
            row[field] = None
    return row
