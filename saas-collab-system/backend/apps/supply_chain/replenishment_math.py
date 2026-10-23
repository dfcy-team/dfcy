"""Pure calendar-day forecast math. Quantities are Decimal until final order rounding."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal


def daily_requirement(daily, day, activity_start=None, activity_end=None, activity_factor=Decimal(1)):
    factor = Decimal(activity_factor) if activity_start and activity_end and activity_start <= day <= activity_end else Decimal(1)
    return Decimal(daily) * factor


def forecast_timeline(*, daily, today, lead_days, cycle_days, safety_days, stock, eta_rows,
                      activity_start=None, activity_end=None, activity_factor=Decimal(1)):
    """Forecast tomorrow through the target horizon, arrivals available before daily sales.

    Unknown/past ETA quantities never silently count as timely arrivals. Callers must
    separately block usable recommendations if supply completeness is unproven.
    """
    reminder_days = lead_days + safety_days
    horizon = reminder_days + cycle_days
    if not 1 <= horizon <= 366:
        raise ValueError('Forecast horizon must be between 1 and 366 days.')
    if daily is None:
        return {'target_stock': None, 'reminder_stock': None, 'reminder_incoming': None,
                'target_incoming': None, 'first_shortage_date': None, 'on_hand_days': None,
                'needs_replenishment': None, 'arrival_gap': None}
    daily = Decimal(daily)
    arrivals = defaultdict(Decimal)
    for row in eta_rows:
        raw = row.get('expected_date')
        if not raw:
            continue
        moment = raw if isinstance(raw, date) else date.fromisoformat(raw)
        quantity = Decimal(str(row['quantity']))
        if quantity < 0:
            raise ValueError('Incoming quantity cannot be negative.')
        if moment < today:
            continue
        # A confirmed ETA today is available for the first forecast sales day.
        arrivals[max(moment, today + timedelta(days=1))] += quantity
    target = reminder = target_incoming = reminder_incoming = Decimal(0)
    balance = Decimal(stock) if stock is not None else None
    shortage = None
    for offset in range(1, horizon + 1):
        day = today + timedelta(days=offset)
        demand = daily_requirement(daily, day, activity_start, activity_end, activity_factor)
        target += demand
        incoming = arrivals[day]
        target_incoming += incoming
        if offset <= reminder_days:
            reminder += demand
            reminder_incoming += incoming
        if balance is not None:
            balance += incoming - demand
            if balance < 0 and shortage is None:
                shortage = day
    coverage = None
    if stock is not None and daily > 0:
        remaining = max(Decimal(0), Decimal(stock))
        coverage = remaining / daily
        if activity_start and activity_end and activity_end > today:
            before_days = max(0, (activity_start - today).days - 1)
            activity_days = (activity_end - max(activity_start, today + timedelta(days=1))).days + 1
            before_qty = daily * before_days
            event_daily = daily * Decimal(activity_factor)
            if event_daily <= 0:
                raise ValueError('Activity factor must be positive.')
            if remaining > before_qty:
                remaining -= before_qty
                if remaining <= event_daily * activity_days:
                    coverage = Decimal(before_days) + remaining / event_daily
                else:
                    coverage = Decimal(before_days + activity_days) + (remaining - event_daily * activity_days) / daily
    return {'target_stock': target, 'reminder_stock': reminder,
            'reminder_incoming': reminder_incoming, 'target_incoming': target_incoming,
            'first_shortage_date': shortage.isoformat() if shortage else None,
            'on_hand_days': coverage.quantize(Decimal('0.01')) if coverage is not None else None,
            'needs_replenishment': (Decimal(stock) + reminder_incoming < reminder) if stock is not None else None,
            'arrival_gap': shortage is not None and shortage <= today + timedelta(days=lead_days)}
