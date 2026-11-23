"""Production verification in a SQL read-only transaction, no business writes."""
from datetime import datetime, timezone
import json
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.influencers.views import OutreachTaskCollectionView, SampleFulfillmentCollectionView

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    actor = get_user_model().objects.get(pk=1, tenant_id=1)
    verified = []
    for view in [OutreachTaskCollectionView, SampleFulfillmentCollectionView]:
        for bounds in [{'created_from': '2026-11-05', 'created_to': '2026-11-05'},
                       {'created_from': '2026-11-05'}, {'created_to': '2026-11-04'},
                       {'created_from': '2026-11-06', 'created_to': '2026-11-05'}]:
            request = APIRequestFactory().get('/api/date-verification/', {**bounds, 'page': 1, 'page_size': 2}, HTTP_HOST='xtsy.dingfengchuangyu.com')
            force_authenticate(request, user=actor)
            response = view.as_view()(request)
            invalid = bounds.get('created_from', '') > bounds.get('created_to', '9999')
            assert response.status_code == (400 if invalid else 200), (view.__name__, response.status_code)
            if not invalid:
                data = response.data['data']
                rows = data.get('results', data.get('items', [])) if isinstance(data, dict) else data
                assert isinstance(rows, list)
                for row in rows:
                    instant = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
                    if bounds.get('created_from'):
                        assert instant >= datetime(2026, 11, 4, 16, tzinfo=timezone.utc)
                    if bounds.get('created_to'):
                        limit = datetime(2026, 11, 5 if bounds['created_to'] == '2026-11-05' else 4, 16, tzinfo=timezone.utc)
                        assert instant < limit
                count = data.get('count', data.get('total')) if isinstance(data, dict) else len(data)
                assert isinstance(count, int) and len(rows) == min(count, 2)
            else:
                count = None
            verified.append({'view': view.__name__, 'params': bounds, 'http': response.status_code, 'count': count})
    print(json.dumps({'read_only': True, 'checks': verified}))
