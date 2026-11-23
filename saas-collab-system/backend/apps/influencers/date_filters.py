"""Inclusive Beijing calendar dates expressed as indexed datetime bounds."""
from datetime import date, datetime, time, timedelta, timezone


def created_date_bounds(start='', end=''):
    def parse(value):
        if not value:
            return None
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError('Expected YYYY-MM-DD.')
        return parsed

    first, last = parse(start), parse(end)
    if first and last and first > last:
        raise ValueError('Start date must not exceed end date.')
    zone = timezone(timedelta(hours=8))
    bounds = {}
    if first:
        bounds['created_at__gte'] = datetime.combine(first, time.min, zone)
    if last:
        bounds['created_at__lt'] = datetime.combine(last + timedelta(days=1), time.min, zone)
    return bounds
