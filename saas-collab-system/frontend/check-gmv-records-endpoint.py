import json
import time
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.integrations.views import integration_workspace_view
user=get_user_model().objects.get(username='root',tenant_id=1,is_active=True)
assert user.is_superuser
for source,resource in [('gmv_max','gmv_max_report'),('video','video_metrics'),('creator','creator_profile')]:
    request=APIRequestFactory().get('/api/internal/integrations/workspace/',
        {'mode':'sync-runs','record_source':source,'resource_type':resource,'page_size':1})
    force_authenticate(request,user=user)
    started=time.monotonic()
    response=integration_workspace_view(request)
    assert response.status_code==200, response.status_code
    data=response.data['data']
    print(json.dumps({'source':source,'status':response.status_code,'seconds':round(time.monotonic()-started,3),
        'total':data['pagination']['total'],'returned':len(data['results'])}),flush=True)
