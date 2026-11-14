"""Warehouse refresh policy based on fulfillment changes, not every order update."""
from datetime import timedelta
import hashlib
import json
from django.utils import timezone


TERMINAL = {'completed', 'cancelled', 'canceled'}


def unpaid(order):
    return not order.paid_at_utc and str(order.raw_status or '').upper() in {'UNPAID', 'PENDING_PAYMENT', 'AWAITING_PAYMENT'}


def fingerprint(order):
    details = order.source_details or {}
    packages = list(details.get('packages') or []) + list((details.get('platform_logistics') or {}).get('packages') or [])
    identities = sorted({tuple(str(pack.get(key) or '') for key in ('package_number', 'package_id', 'tracking_number'))
                         for pack in packages if isinstance(pack, dict)})
    digest = hashlib.sha256(json.dumps([order.store_id, identities], sort_keys=True).encode()).hexdigest()
    return [order.raw_status, order.normalized_status, str(order.paid_at_utc or ''), digest]


def complete_shipment(packages):
    return bool(packages) and all(pack.get('shipped_at_utc') and pack.get('tracking_no') and pack.get('items')
        and all(item.get('quantity') is not None and (item.get('sku') or item.get('warehouse_sku')) for item in pack['items'])
        for pack in packages)


def next_refresh(row, order, state, checks, packages):
    now = timezone.now()
    if not row.polling_until or row.polling_until <= now or order.normalized_status in TERMINAL or unpaid(order):
        return None, row.retry_count
    if state == 'matched':
        return (None if complete_shipment(packages) else min(now + timedelta(hours=1), row.polling_until)), 0
    if state == 'conflict' or any('尚未适配' in check.get('message', '') for check in checks):
        return None, row.retry_count
    if state == 'blocked' or any(check.get('status') == 'blocked' for check in checks):
        # The dispatcher checks local readiness only before resuming a blocked query.
        return min(now + timedelta(hours=1), row.polling_until), row.retry_count
    delays = (10, 30, 120)
    if row.retry_count >= len(delays):
        return None, row.retry_count
    return min(now + timedelta(minutes=delays[row.retry_count]), row.polling_until), row.retry_count + 1
