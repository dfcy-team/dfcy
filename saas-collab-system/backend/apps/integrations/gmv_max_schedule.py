"""Bounded GMV Max rolling refresh; no scheduling or credentials at import time."""
from datetime import timedelta
from zoneinfo import ZoneInfo


def safe_error_code(exc):
    detail = str(getattr(exc, 'detail', ''))
    for message, code in (
        ('GMV Max store identity/exclusive advertiser is not verified.', 'gmv_max_store_not_verified'),
        ('Empty GMV Max report is not evidence of zero spend.', 'empty_report_not_zero'),
        ('Shop authorization has expired.', 'shop_authorization_expired'),
        ('GMV Max official read rejected; no data committed.', 'provider_read_rejected'),
        ('Advertiser identity/currency/timezone mismatch.', 'advertiser_metadata_changed'),
    ):
        if message in detail:
            return code
    return 'validation_or_collection_failed'


def complete_days(now, timezone_name):
    if now.tzinfo is None:
        raise ValueError('An aware clock is required.')
    today = now.astimezone(ZoneInfo(timezone_name)).date()
    return [today - timedelta(days=n) for n in range(7, 0, -1)]


def collect_days(days, collect, emit):
    counts = {'success': 0, 'failed': 0}
    for day in days:
        try:
            result = collect(day)
            if result.get('committed') is not True:
                raise ValueError('Collection did not commit verified evidence.')
        except Exception as exc:
            counts['failed'] += 1
            # Provider exception text can contain credentials or request URLs.
            emit({'date': day.isoformat(), 'status': 'failed',
                  'error_type': type(exc).__name__, 'error_code': safe_error_code(exc)})
        else:
            counts['success'] += 1
            emit({'date': day.isoformat(), 'status': 'success', 'result': result})
    return counts
