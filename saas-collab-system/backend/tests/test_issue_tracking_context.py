import pytest
from unittest.mock import patch
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant, Department

@pytest.mark.django_db
def test_record_candidates_require_requester_business_access():
    tenant=Tenant.objects.create(code='tracking-candidate-requester',name='local')
    user=CustomUser.objects.create_user(username='candidate-requester',tenant=tenant,user_type='internal')
    client=APIClient(); client.force_authenticate(user)
    with patch('apps.issue_tracking.links.can_access_page',return_value=True), patch('apps.issue_tracking.links.can_access_record',return_value=False):
        response=client.get('/api/internal/issue-tracking/candidates/',{'menu_key':'/supply-chain/purchase-orders','record_type':'purchase_order','record_id':'17'})
    assert response.status_code==403
    assert 'users' not in response.data.get('data',{}) if isinstance(response.data.get('data'),dict) else True

@pytest.mark.django_db
def test_linked_record_cannot_bypass_menu_rule_by_omitting_menu():
    tenant=Tenant.objects.create(code='tracking-no-menu',name='local')
    department=Department.objects.create(tenant=tenant,name='local')
    user=CustomUser.objects.create_user(username='tracking-no-menu',tenant=tenant,user_type='internal')
    client=APIClient(); client.force_authenticate(user)
    response=client.post('/api/internal/issue-tracking/issues/',{'title':'invalid','assignee':user.pk,'department':department.pk,'due_at':timezone.now().isoformat(),'page_path':'/workflow/approvals'},format='json')
    assert response.status_code==400


@pytest.mark.django_db
def test_creator_note_does_not_start_handler_feedback_clock():
    from apps.issue_tracking.models import Issue
    tenant=Tenant.objects.create(code='tracking-feedback-clock',name='local')
    department=Department.objects.create(tenant=tenant,name='local')
    creator=CustomUser.objects.create_user(username='clock-creator',tenant=tenant,user_type='internal')
    handler=CustomUser.objects.create_user(username='clock-handler',tenant=tenant,user_type='internal')
    issue=Issue.objects.create(tenant=tenant,creator=creator,assignee=handler,department=department,title='clock',due_at=timezone.now())
    client=APIClient(); client.force_authenticate(creator)
    path=f'/api/internal/issue-tracking/issues/{issue.pk}/actions/'
    response=client.post(path,{'action':'feedback','content':'发起人补充说明'},format='json')
    assert response.data['data']['first_feedback_at'] is None
    client.force_authenticate(handler)
    response=client.post(path,{'action':'feedback','content':'处理人开始反馈'},format='json')
    assert response.data['data']['first_feedback_at'] is not None
    assert response.data['data']['last_feedback_at'] is not None
