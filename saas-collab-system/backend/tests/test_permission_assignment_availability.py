import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from apps.permissions.assignment_availability import MODULE_PATH_PREFIXES, module_for_path, unavailable_assignment_codes
from tests.test_inactive_role_assignment import assign, setup_assignment
from rest_framework.test import APIClient
from apps.permissions.models import Permission
from apps.audit.models import OperationLog

def test_assignment_release_paths_match_frontend_and_specific_paths_win():
    source=(Path(__file__).parents[2]/'frontend/src/router/menu.js').read_text(encoding='utf-8')
    block=source.split('const modulePathPrefixes = [',1)[1].split('];',1)[0]
    assert tuple(re.findall(r"\['([^']+)', '([^']+)'\]",block)) == MODULE_PATH_PREFIXES
    assert module_for_path('/products/research')=='product_development'
    assert module_for_path('/products/platform-details')=='masterdata'

def test_shared_permission_remains_available_when_any_registered_page_is_enabled():
    menus=[{'code':'menu.disabled','metadata':{'path':'/listings/online','action_codes':['listings.product_detail.view']}},{'code':'menu.enabled','metadata':{'path':'/products/platform-details','action_codes':['listings.product_detail.view']}}]
    permissions=[SimpleNamespace(code='listings.product_detail.manage',permission_type='action',module='listings'),SimpleNamespace(code='rpa.devices.manage',permission_type='action',module='rpa')]
    assert unavailable_assignment_codes(permissions,statuses={'global_listing':'disabled','masterdata':'enabled','rpa':'disabled'},menus=menus)=={'menu.disabled','rpa.devices.manage'}

@pytest.mark.django_db
def test_stopped_module_new_grant_rejected_existing_history_preserved_and_copy_excludes_it():
    actor,role=setup_assignment('superuser','release-stopped')
    client=APIClient();client.force_authenticate(actor)
    code='menu.products.products_research.view'
    permission,_=Permission.objects.get_or_create(code=code,defaults={'name':'新品市调','module':'products','action':'products_research.view','permission_type':'menu'})
    with patch('apps.permissions.assignment_availability.module_statuses',return_value={'product_development':'disabled','masterdata':'enabled','system':'enabled'}):
        response=assign(client,role,[code,'reports.view'])
        assert response.status_code==400
        assert not role.permissions.exists()
        role.permissions.add(permission)
        response=assign(client,role,['reports.view'])
        assert response.status_code==200,response.content
        assert role.permissions.filter(code=code).exists()
        copy=client.post(f'/api/internal/system/roles/{role.pk}/copy/',{'name':'复制有效授权','code':'released-copy'},format='json')
        assert copy.status_code in (200,201),copy.content
        assert code not in copy.json()['data']['permission_codes']
        assert role.permissions.filter(code=code).exists()
        log=OperationLog.objects.get(tenant=actor.tenant,action='role_copy',object_id=str(copy.json()['data']['id']))
        assert code in log.before_data['permissions']
        assert code not in log.after_data['permissions']
        assert set(log.after_data['permissions']) == set(copy.json()['data']['permission_codes'])
