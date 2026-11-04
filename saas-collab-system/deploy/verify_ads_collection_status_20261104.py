"""Read-only API and financial-fingerprint verification, in an isolated process."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import types

candidate = os.environ.get('ADS_STATUS_CANDIDATE_DIR')
if candidate:
    modules = [('apps.integrations.gmv_max_schedule', '2'),
               ('apps.integrations.gmv_max_sync', '3'),
               ('apps.integrations.gmv_max_read', '1'),
               ('apps.integrations.gmv_max_overview', '0'),
               ('apps.reports.tiktok_ads_services', '5')]
    for name, slot in modules:
        path = Path(candidate) / slot
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = name.rsplit('.', 1)[0]
        sys.modules[name] = module
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
        setattr(importlib.import_module(module.__package__), name.rsplit('.', 1)[1], module)

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.reports.tiktok_ads_views import tiktok_daily_spend

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    user = get_user_model().objects.get(username='root', tenant_id=1)
    request = APIRequestFactory().get('/api/internal/analytics/advertising/tiktok-daily-spend/', {
        'report_type': 'gmv_max', 'date_from': '2026-10-28', 'date_to': '2026-11-03'})
    force_authenticate(request, user=user)
    started = time.monotonic()
    response = tiktok_daily_spend(request)
    assert response.status_code == 200, response.status_code
    data = response.data['data']
    assert data['scope'] == 'GMVMax'
    assert 'BASIC/AUCTION_CAMPAIGN' in data['excludes']
    assert 'totals' not in data and 'results' not in data
    rows = data['gmv_max_snapshots']
    assert rows is not None
    money = sorted([{k: r[k] for k in ('store_code', 'advertiser_id', 'platform_store_id',
        'date', 'currency', 'timezone', 'cost', 'gross_revenue', 'orders')} for r in rows],
        key=lambda r: (r['store_code'], r['advertiser_id'], r['date'], r['currency'], r['timezone']))
    digest = hashlib.sha256(json.dumps(money, sort_keys=True).encode()).hexdigest()
    status = data.get('gmv_max_collection_days')
    if os.environ.get('ADS_STATUS_REQUIRE_NEW') == '1':
        assert status is not None
        for store, day, adv in [('TK1PH', '2026-11-03', '7651940663654678546'),
                                ('TK9PH', '2026-10-31', '7666280302165262344'),
                                ('TKKJ1PH', '2026-10-30', '7654416388122624008')]:
            match = [r for r in status if r['store_code'] == store and r['date'] == day
                     and r['advertiser_id'] == adv]
            assert len(match) == 1 and match[0]['status'] == 'success', (store, day)
        from apps.integrations.gmv_max_sync import summarize
        empty = summarize([{'page_info': {'page': 1, 'page_size': 100,
            'total_page': 0, 'total_number': 0}, 'list': []}])
        assert empty['collection_status'] == 'no_data' and empty['cost'] is None
    print(json.dumps({'http_status': response.status_code, 'scope': data['scope'],
        'rows': len(rows), 'shop_groups': len(data['gmv_max_shop_overview']),
        'financial_sha256': digest, 'collection_days': len(status) if status is not None else None,
        'status_counts': {s: sum(r['status'] == s for r in status) for s in
            ['success', 'no_data', 'failed', 'not_collected']} if status is not None else None,
        'seconds': round(time.monotonic() - started, 3), 'warnings': data['warnings']}))
