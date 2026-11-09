"""Authenticated SELECT-only check of the deployed DRF endpoint."""
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.integrations.views import integration_workspace_view

user = get_user_model().objects.get(pk=1, tenant_id=1)
for source in ('video', 'creator', 'invalid'):
    request = APIRequestFactory().get('/api/internal/integrations/workspace/',
        {'mode': 'sync-runs', 'record_source': source, 'page_size': 2})
    force_authenticate(request, user=user)
    response = integration_workspace_view(request)
    response.render()
    assert response.status_code == (400 if source == 'invalid' else 200), response.data
    if source != 'invalid':
        print(source, response.status_code, response.data['data']['pagination'])
    else:
        print('invalid source rejected', response.status_code)
