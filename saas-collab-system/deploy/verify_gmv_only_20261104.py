import json
import time
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.reports.tiktok_ads_views import tiktok_daily_spend

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    user = get_user_model().objects.get(username='root', tenant_id=1)
    req = APIRequestFactory().get('/api/reports/tiktok-daily-spend/', {
        'report_type': 'gmv_max', 'date_from': '2026-10-28', 'date_to': '2026-11-03'})
    force_authenticate(req, user=user)
    start = time.monotonic()
    response = tiktok_daily_spend(req)
    data = response.data.get('data', response.data)
    assert response.status_code == 200, response.status_code
    assert data['scope'] == 'GMVMax'
    rows = data['gmv_max_snapshots']
    assert rows is not None
    print(json.dumps({'http_status': response.status_code,
        'seconds': round(time.monotonic() - start, 3), 'scope': data['scope'],
        'rows': len(rows), 'positive_cost_rows': sum(Decimal(r['cost']) > 0 for r in rows),
        'shop_groups': len(data['gmv_max_shop_overview']),
        'warnings': data['warnings'], 'response_keys': list(data)}, ensure_ascii=True))
