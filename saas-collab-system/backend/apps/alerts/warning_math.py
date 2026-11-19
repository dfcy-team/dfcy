"""Country inventory warning math. No ORM, network, or invented arrival dates."""
from datetime import date, timedelta
from decimal import Decimal
from math import ceil
from fractions import Fraction


def number(value):
    return None if value is None else Decimal(str(value))


def assess_sku(*, stock, daily_sales, arrivals, today, horizon_days=60,
               production_unshipped=0, supply_authorized=True, supply_complete=True,
               sales_complete=True, inventory_complete=True,
               first_sale_date=None, observation_days=30, activity_start=None,
               activity_end=None, activity_factor=1, daily_ratio=None):
    horizon_days = max(1, min(366, int(horizon_days)))
    stock, daily = number(stock), number(daily_sales)
    result = {'state': 'ready', 'first_shortage_date': None,
              'maximum_shortage_quantity': None, 'next_confirmed_arrival_date': None, 'overdue_quantity': '0',
              'unknown_arrival_quantity': '0', 'production_unshipped': str(production_unshipped or 0),
              'warnings': [], 'new_product': False}
    scheduled = {}
    overdue = unknown = Decimal(0)
    for row in arrivals if supply_authorized else []:
        qty = max(Decimal(0), number(row.get('quantity')) or Decimal(0))
        raw = row.get('expected_date')
        day = date.fromisoformat(raw[:10]) if isinstance(raw, str) and raw else raw
        if day is None:
            unknown += qty
        elif day < today:
            overdue += qty
        else:
            scheduled[day] = scheduled.get(day, Decimal(0)) + qty
    result.update(overdue_quantity=str(overdue), unknown_arrival_quantity=str(unknown),next_confirmed_arrival_date=min((day for day,qty in scheduled.items() if qty>0),default=None).isoformat() if any(qty>0 for qty in scheduled.values()) else None)
    if overdue:
        result['warnings'].append('supply_overdue')
    if unknown or number(production_unshipped or 0) > 0:
        result['warnings'].append('arrival_unconfirmed')
    if first_sale_date:
        first = date.fromisoformat(first_sale_date[:10]) if isinstance(first_sale_date, str) else first_sale_date
        result['new_product'] = 0 <= (today-first).days < observation_days
        if result['new_product']:result['warnings'].append('new_product_observation')
    if not inventory_complete or stock is None or not sales_complete or daily is None:
        result['state'] = 'unavailable'
        return result
    if daily < 0:
        raise ValueError('Daily demand must be nonnegative')
    # A forecast requires complete supply visibility. Unknown dates are never
    # substituted with lead-time estimates, but remain separate action items.
    if not supply_authorized or not supply_complete:
        result['state'] = 'unavailable'
        return result
    activity_start = date.fromisoformat(activity_start) if isinstance(activity_start, str) else activity_start
    activity_end = date.fromisoformat(activity_end) if isinstance(activity_end, str) else activity_end
    activity_factor = number(activity_factor)
    if activity_factor is None or activity_factor < 0:
        raise ValueError('Activity multiplier must be nonnegative')
    daily = Fraction(*daily_ratio) if daily_ratio is not None else Fraction(daily)
    activity_factor = Fraction(activity_factor)
    balance = Fraction(stock) + Fraction(scheduled.get(today, Decimal(0)))
    target_stock = Fraction(0)
    low = min(balance, Fraction(0))
    first_shortage = today if stock <= 0 and daily > 0 else None
    for offset in range(1, horizon_days + 1):
        day = today + timedelta(days=offset)
        demand = daily * activity_factor if activity_start and activity_end and activity_start <= day <= activity_end else daily
        target_stock += demand
        balance += Fraction(scheduled.get(day, Decimal(0))) - demand
        low = min(low, balance)
        if balance < 0 and first_shortage is None:
            first_shortage = day
    if first_shortage:
        result['first_shortage_date'] = first_shortage.isoformat()
        result['warnings'].append('forecast_stockout')
        if any(day>first_shortage and qty>0 for day,qty in scheduled.items()):
            result['warnings'].append('arrival_after_shortage')
    result['maximum_shortage_quantity'] = ceil(-low)
    result['target_stock'] = str(Decimal(target_stock.numerator) / Decimal(target_stock.denominator))
    if first_sale_date and stock > 0 and daily == 0 and not result['new_product']:
        result['warnings'].append('stock_without_sales')
    elif first_sale_date and daily > 0 and stock > target_stock and not result['new_product']:
        result['warnings'].append('excess_stock')
    return result


def assess_spu(rows, *, key_sales_share=Decimal('0.80')):
    """Include complete SPU siblings; rank equal-volume variants together."""
    total = sum((max(Decimal(0), number(r.get('sales_quantity')) or Decimal(0)) for r in rows), Decimal(0))
    ranked = sorted(rows, key=lambda r: -(number(r.get('sales_quantity')) or Decimal(0)))
    before = Decimal(0)
    previous_units = None
    group_before = Decimal(0)
    key_ids, shortage_ids = [], []
    for row in ranked:
        units = max(Decimal(0), number(row.get('sales_quantity')) or Decimal(0))
        # Threshold at group start preserves ties.
        if units != previous_units:
            group_before = before
            previous_units = units
        if total and units and group_before / total < key_sales_share:
            key_ids.append(row['sku_id'])
            if 'forecast_stockout' in row.get('warning', {}).get('warnings', []):
                shortage_ids.append(row['sku_id'])
        before += units
    affected = sum((number(r.get('sales_quantity')) or Decimal(0) for r in rows if r['sku_id'] in shortage_ids), Decimal(0))
    return {'key_sku_ids': key_ids, 'key_shortage_sku_ids': shortage_ids,
            'key_shortage_sales_share': str(affected / total) if total else None}
