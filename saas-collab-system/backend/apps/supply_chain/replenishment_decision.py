"""Quantity and arrival decisions using disjoint purchase/shipment stages."""
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from math import ceil, lcm


def round_purchase(quantity, *, purchase_multiple=1, carton_quantity=1, minimum_order=0):
    """Keep demand visible while respecting all configured purchase units."""
    if quantity <= 0:
        return 0
    multiple = lcm(purchase_multiple, carton_quantity)
    return ceil(Fraction(max(quantity, minimum_order), multiple)) * multiple


def calculate_decision(*, daily_sales, available_stock, production_unshipped,
                       shipment_rows, submitted_demand=0, draft_reserved=0,
                       today, lead_days, cycle_days, safety_days,
                       purchase_multiple=1, carton_quantity=1, minimum_order=0,
                       orderable=True, daily_ratio=None, activity_start=None, activity_end=None,
                       activity_factor=1):
    """Arrivals affect urgency; all outstanding supply reduces purchase demand."""
    if min(lead_days, cycle_days, safety_days) < 0 or lead_days + cycle_days + safety_days < 1:
        raise ValueError("Coverage must be positive.")
    if purchase_multiple < 1 or carton_quantity < 1 or minimum_order < 0:
        raise ValueError("Purchase quantities must be nonnegative with positive multiples.")
    if daily_sales is None or available_stock is None:
        return {"category": "unavailable", "suggested_quantity": None, "can_order": False}
    daily = Fraction(*daily_ratio) if daily_ratio else Fraction(Decimal(str(daily_sales)))
    stock = Fraction(Decimal(str(available_stock)))
    production = max(Fraction(0), Fraction(Decimal(str(production_unshipped or 0))))
    submitted = max(Fraction(0), Fraction(Decimal(str(submitted_demand or 0))))
    reserved = max(Fraction(0), Fraction(Decimal(str(draft_reserved or 0))))
    if daily < 0:
        raise ValueError("Daily demand cannot be negative.")
    incoming = Fraction(0)
    arrivals = {}
    estimated = 0
    for row in shipment_rows:
        quantity = max(Fraction(0), Fraction(Decimal(str(row["quantity"]))))
        incoming += quantity
        raw = row.get("expected_date")
        arrival = date.fromisoformat(raw) if isinstance(raw, str) else raw
        if arrival is None or arrival < today:
            arrival = today + timedelta(days=lead_days)
            estimated += 1
        arrival = max(today + timedelta(days=1), arrival)
        arrivals[arrival] = arrivals.get(arrival, Fraction(0)) + quantity
    production_date = today + timedelta(days=max(1, lead_days))
    arrivals[production_date] = arrivals.get(production_date, Fraction(0)) + production
    horizon = lead_days + cycle_days + safety_days
    activity_days = 0
    if activity_start and activity_end:
        first = max(today + timedelta(days=1), activity_start)
        last = min(today + timedelta(days=horizon), activity_end)
        activity_days = max(0, (last - first).days + 1)
    target = daily * (horizon + activity_days * (Fraction(Decimal(str(activity_factor))) - 1))
    raw_quantity = max(0, ceil(target - stock - incoming - production - submitted - reserved))
    suggested = round_purchase(raw_quantity, purchase_multiple=purchase_multiple,
                               carton_quantity=carton_quantity, minimum_order=minimum_order) if orderable else 0
    balance = stock
    first_shortage = None
    for offset in range(1, lead_days + cycle_days + safety_days + 1):
        day = today + timedelta(days=offset)
        demand = daily
        if activity_start and activity_end and activity_start <= day <= activity_end:
            demand *= Fraction(Decimal(str(activity_factor)))
        balance += arrivals.get(day, Fraction(0)) - demand
        if balance < 0 and first_shortage is None:
            first_shortage = day
    earliest_new_arrival = today + timedelta(days=max(1, lead_days))
    requires_expedite = bool(first_shortage is not None and orderable and
                            (suggested == 0 or first_shortage < earliest_new_arrival))
    if not orderable:
        category = "inactive"
    elif suggested > 0:
        category = "purchase"
    elif first_shortage is not None:
        category = "expedite"
    elif stock > 0 and daily == 0:
        category = "no_sales"
    elif stock == 0 and daily == 0 and incoming == 0 and production == 0:
        category = "hidden"
    else:
        category = "sufficient"
    return {"category": category, "suggested_quantity": suggested,
            "raw_purchase_quantity": raw_quantity, "rounding_quantity": suggested - raw_quantity if orderable else 0,
            "can_order": orderable and suggested > 0,
            "first_shortage_date": first_shortage.isoformat() if first_shortage else None,
            "requires_expedite": requires_expedite,
            "estimated_arrival_count": estimated,
            "target_stock": str(Decimal(target.numerator) / Decimal(target.denominator)),
            "available_stock": str(available_stock), "incoming_quantity": str(Decimal(incoming.numerator) / Decimal(incoming.denominator)),
            "production_unshipped": str(production_unshipped or 0),
            "submitted_demand": str(submitted_demand or 0), "draft_reserved": str(draft_reserved or 0)}
