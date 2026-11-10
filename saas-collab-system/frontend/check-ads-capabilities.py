import json
import time
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.integrations.ads_capability_api import capabilities

user = get_user_model().objects.get(username='root', tenant_id=1, is_active=True)
assert user.is_superuser
request = APIRequestFactory().get('/api/internal/integrations/tiktok-ads/capabilities/')
force_authenticate(request, user=user)
started = time.monotonic()
response = capabilities(request)
rows = response.data['data']['items']
print(json.dumps({'status': response.status_code, 'seconds': round(time.monotonic()-started, 3),
    'count': len(rows), 'verified': sum(r['verification_state']=='verified' for r in rows),
    'read_enabled': sum(r['read_enabled'] for r in rows)}, ensure_ascii=False))
