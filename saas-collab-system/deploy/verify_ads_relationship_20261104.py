"""Isolated read-only view verification; never modifies mappings or report amounts."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import types

stage = os.environ.get('ADS_RELATION_STAGE')
if stage:
    root = Path(stage)
    sources = [('apps.integrations.gmv_max_relationship', root / 'candidate/backend/apps/integrations/gmv_max_relationship.py'),
        ('apps.integrations.gmv_max_sync', root / 'after/1'),
        ('apps.integrations.gmv_max_read', root / 'after/0'),
        ('apps.reports.tiktok_ads_services', root / 'after/3')]
    for name, path in sources:
        module = types.ModuleType(name)
        module.__package__ = name.rsplit('.', 1)[0]
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
        setattr(importlib.import_module(module.__package__), name.rsplit('.', 1)[1], module)

from django.contrib.auth import get_user_model
from django.db import transaction, connection
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.reports.tiktok_ads_views import tiktok_daily_spend

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    actor = get_user_model().objects.get(pk=1, tenant_id=1)
    request = APIRequestFactory().get('/api/internal/analytics/advertising/tiktok-daily-spend/', {
        'report_type': 'gmv_max', 'date_from': '2026-10-28', 'date_to': '2026-11-03'})
    force_authenticate(request, user=actor)
    response = tiktok_daily_spend(request)
    assert response.status_code == 200
    data = response.data['data']
    assert data['scope'] == 'GMVMax'
    rows = data['gmv_max_snapshots']
    money = sorted([{k: r[k] for k in ('store_code', 'advertiser_id', 'platform_store_id',
        'date', 'currency', 'timezone', 'cost', 'gross_revenue', 'orders')} for r in rows],
        key=lambda r: (r['store_code'], r['advertiser_id'], r['date'], r['currency'], r['timezone']))
    digest = hashlib.sha256(json.dumps(money, sort_keys=True).encode()).hexdigest()
    assert digest == '96592ae6d5d7d37c3e49c564c8003a087507d572f24b0f8b217ad09c248378c9'
    examples = []
    for code in ['TKKJ2PH', 'TKKJ3PH']:
        group = next(g for g in data['gmv_max_shop_overview'] if g['store_code'] == code)
        c = group['api_coverage']
        assert c['account_count'] == 1 and c['stored_days'] == c['expected_days'] == 7 and c['complete']
        examples.append({'store': code, 'coverage': c})
    observations = data['gmv_max_relationships']
    if os.environ.get('ADS_RELATION_REQUIRE_PROBE') == '1':
        current = next(r for r in observations if r['mapping_id'] == 24)
        historical = next(r for r in observations if r['mapping_id'] == 25)
        assert current['relationship_status'] == 'current_verified' and current['fresh']
        assert historical['relationship_status'] == 'not_current' and historical['fresh']
        assert current['platform_store_id'] == historical['platform_store_id']
        assert current['exclusive_advertiser_id'] == historical['exclusive_advertiser_id'] == current['advertiser_id']
    print(json.dumps({'verified': True, 'http_status': response.status_code, 'scope': data['scope'],
        'rows': len(rows), 'verified_report_relationships': sum(r['relationship_verified'] for r in rows),
        'financial_sha256': digest, 'examples': examples,
        'relationship_observations': len(observations)}))
