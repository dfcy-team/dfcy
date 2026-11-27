from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant, Department
from apps.issue_tracking.models import Issue, Notification, ManagementGrant

URL = '/api/internal/issue-tracking/notification-center/'

def context(suffix):
    tenant = Tenant.objects.create(name=suffix, code='bell-'+suffix)
    department = Department.objects.create(tenant=tenant, name='department')
    owner = CustomUser.objects.create_user(username='bell-owner-'+suffix, tenant=tenant, user_type='internal')
    issue = Issue.objects.create(tenant=tenant, creator=owner, assignee=owner, department=department, title='消息标题', due_at=timezone.now()+timedelta(days=1))
    client = APIClient(); client.force_authenticate(owner)
    return tenant, department, owner, issue, client

@pytest.mark.django_db
def test_notification_count_is_not_page_limited_and_read_operations_are_scoped():
    tenant, _, owner, issue, client = context('count')
    Notification.objects.bulk_create([Notification(issue=issue, recipient=owner, action='assigned') for _ in range(105)])
    Notification.objects.create(issue=issue, recipient=owner, action='close', read_at=timezone.now())
    other = CustomUser.objects.create_user(username='bell-other',tenant=tenant,user_type='internal')
    foreign = Notification.objects.create(issue=issue,recipient=other,action='assigned')
    other_tenant, _, outsider, other_issue, _ = context('foreign')
    outside = Notification.objects.create(issue=other_issue,recipient=outsider,action='assigned')
    result=client.get(URL).data['data']
    assert result['unread_count']==105 and result['count']==105 and len(result['results'])==20
    assert result['results'][0]['issue_title']=='消息标题'
    identity=result['results'][0]['id']
    result=client.post(URL,{'id':identity},format='json').data['data']
    assert result=={'updated_count':1,'unread_count':104}
    assert client.post(URL,{'id':identity},format='json').data['data']['updated_count']==0
    assert client.post(URL,{'id':foreign.pk},format='json').status_code==404
    assert client.post(URL,{'id':outside.pk},format='json').status_code==404
    result=client.post(URL,{'all':True},format='json').data['data']
    assert result=={'updated_count':104,'unread_count':0}
    assert client.get(URL).data['data']['results']==[]
    assert client.get(URL,{'view':'all'}).data['data']['count']==106
    foreign.refresh_from_db(); outside.refresh_from_db()
    assert foreign.read_at is None and outside.read_at is None

@pytest.mark.django_db
def test_notification_permissions_are_rechecked_after_grant_revocation():
    tenant, department, _, issue, client = context('revoke')
    manager=CustomUser.objects.create_user(username='bell-manager',tenant=tenant,user_type='internal')
    grant=ManagementGrant.objects.create(tenant=tenant,user=manager,department=department,permissions=['view'])
    notification=Notification.objects.create(issue=issue,recipient=manager,action='remind')
    client.force_authenticate(manager)
    assert client.get(URL).data['data']['unread_count']==1
    grant.delete()
    assert client.get(URL).data['data']['unread_count']==0
    assert client.post(URL,{'id':notification.pk},format='json').status_code==404
    assert client.post(URL,{'all':True},format='json').data['data']['updated_count']==0
    notification.refresh_from_db(); assert notification.read_at is None

@pytest.mark.django_db
def test_notification_invalid_requests_and_unauthenticated_access():
    _, _, _, _, client=context('invalid')
    for payload in [{},{'id':'bad'},{'all':'true'},{'all':True,'id':1}]:
        assert client.post(URL,payload,format='json').status_code==400
    assert client.get(URL,{'view':'invalid'}).status_code==400
    assert client.get(URL,{'page':'bad'}).status_code==400
    client.force_authenticate(None)
    assert client.get(URL).status_code in (401,403)
