import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from apps.tenants.models import Tenant, Department
from apps.accounts.models import CustomUser
from apps.issue_tracking.models import Issue, ManagementGrant

@pytest.mark.django_db
def test_tracking_flow_and_isolation():
    t=Tenant.objects.create(name='t',code='tracking-t')
    d=Department.objects.create(tenant=t,name='d')
    def user(name,tenant=t): return CustomUser.objects.create_user(username=name,tenant=tenant,user_type='internal')
    creator=user('tracking-c'); worker=user('tracking-w'); stranger=user('tracking-s')
    c=APIClient(); c.force_authenticate(creator)
    base='/api/internal/issue-tracking/'
    r=c.post(base+'issues/',{'title':'跟踪','description':'说明','department':d.pk,'assignee':worker.pk,'due_at':(timezone.now()+timedelta(days=1)).isoformat()},format='json')
    assert r.status_code==201,r.data
    pk=r.data['data']['id']; path=base+f'issues/{pk}/actions/'
    c.force_authenticate(stranger)
    assert c.get(base+f'issues/{pk}/').status_code==404
    c.force_authenticate(worker)
    assert c.post(path,{'action':'close','content':'完成'},format='json').status_code==403
    assert c.post(path,{'action':'feedback','content':'处理中'},format='json').data['data']['status']=='processing'
    assert c.post(path,{'action':'submit','content':'完成结果'},format='json').data['data']['status']=='confirming'
    c.force_authenticate(creator)
    assert c.post(path,{'action':'return','content':'补资料'},format='json').data['data']['status']=='processing'
    assert c.post(path,{'action':'remind'},format='json').status_code==200
    assert c.post(path,{'action':'remind'},format='json').status_code==400
    c.force_authenticate(worker)
    c.post(path,{'action':'submit','content':'已补齐'},format='json')
    c.force_authenticate(creator)
    assert c.post(path,{'action':'close','content':'确认完成'},format='json').data['data']['status']=='closed'
    assert c.post(path,{'action':'reopen','content':'继续跟踪'},format='json').data['data']['status']=='processing'
    other=Tenant.objects.create(name='other',code='tracking-other')
    outsider=user('tracking-o',other)
    c.force_authenticate(outsider)
    assert c.get(base+f'issues/{pk}/').status_code==404
    assert c.post(base+'issues/',{'title':'非法','department':d.pk,'assignee':worker.pk,'due_at':timezone.now().isoformat()},format='json').status_code==400

@pytest.mark.django_db
def test_department_grant_expiry_and_descendants():
    from apps.issue_tracking.access import visible, allowed
    t=Tenant.objects.create(name='g',code='tracking-g')
    parent=Department.objects.create(tenant=t,name='parent')
    child=Department.objects.create(tenant=t,name='child',parent=parent)
    users=[CustomUser.objects.create_user(username='tracking-g'+str(i),tenant=t,user_type='internal') for i in range(3)]
    issue=Issue.objects.create(tenant=t,creator=users[0],assignee=users[1],department=child,title='test',due_at=timezone.now())
    grant=ManagementGrant.objects.create(tenant=t,user=users[2],department=parent,permissions=['view','remind'])
    assert not visible(users[2]).exists()
    grant.include_descendants=True; grant.save()
    assert visible(users[2]).filter(pk=issue.pk).exists()
    assert allowed(users[2],issue,'remind')
    assert not allowed(users[2],issue,'close')
    grant.ends_at=timezone.now()-timedelta(seconds=1); grant.save()
    assert not visible(users[2]).exists()


@pytest.mark.django_db
def test_attachment_read_manager_cannot_write_and_config_audit():
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.issue_tracking.models import ConfigurationAudit
    t=Tenant.objects.create(name='a',code='tracking-attachments')
    d=Department.objects.create(tenant=t,name='dept')
    creator=CustomUser.objects.create_user(username='attach-c',tenant=t,user_type='internal')
    manager=CustomUser.objects.create_user(username='attach-m',tenant=t,user_type='internal')
    admin=CustomUser.objects.create_user(username='attach-a',tenant=t,user_type='internal',is_superuser=True)
    issue=Issue.objects.create(tenant=t,creator=creator,assignee=creator,department=d,title='attachment',due_at=timezone.now())
    ManagementGrant.objects.create(tenant=t,user=manager,department=d,permissions=['view'])
    c=APIClient(); c.force_authenticate(creator)
    base='/api/internal/issue-tracking/'
    r=c.post(base+f'issues/{issue.pk}/attachments/',{'file':SimpleUploadedFile('evidence.txt',b'evidence')},format='multipart')
    assert r.status_code==201,r.data
    file_id=r.data['data']['id']
    c.force_authenticate(manager)
    assert c.get(base+f'attachments/{file_id}/download/').status_code==200
    assert c.post(base+f'issues/{issue.pk}/actions/',{'action':'feedback','content':'unauthorized'},format='json').status_code==403
    assert c.post(base+f'issues/{issue.pk}/attachments/',{'file':SimpleUploadedFile('bad.txt',b'bad')},format='multipart').status_code==403
    assert c.post(base+'grants/',{},format='json').status_code==403
    c.force_authenticate(admin)
    r=c.post(base+'grants/',{'user':manager.pk,'department':d.pk,'permissions':['view','remind']},format='json')
    assert r.status_code==201,r.data
    assert r.data['success'] is True
    assert ConfigurationAudit.objects.filter(actor=admin,operation='create').count()==1

@pytest.mark.django_db
def test_reassign_reschedule_transfer_and_history():
    from apps.issue_tracking.models import Notification
    t=Tenant.objects.create(name='flow',code='tracking-flow')
    d=Department.objects.create(tenant=t,name='from'); dest=Department.objects.create(tenant=t,name='to')
    users=[CustomUser.objects.create_user(username='flow'+str(i),tenant=t,user_type='internal') for i in range(4)]
    issue=Issue.objects.create(tenant=t,creator=users[0],assignee=users[1],department=d,title='old',due_at=timezone.now()-timedelta(days=2))
    c=APIClient(); c.force_authenticate(users[3]); base='/api/internal/issue-tracking/'; path=base+f'issues/{issue.pk}/actions/'
    grant=ManagementGrant.objects.create(tenant=t,user=users[3],department=d,permissions=['view','reassign','transfer','reschedule'])
    assert c.post(path,{'action':'transfer','department':dest.pk,'content':'移交'},format='json').status_code==403
    ManagementGrant.objects.create(tenant=t,user=users[3],department=dest,permissions=['view','transfer'])
    assert c.post(path,{'action':'reassign','assignee':users[2].pk,'content':'换人'},format='json').status_code==200
    issue.refresh_from_db(); assert issue.department_id==d.pk
    assert c.post(path,{'action':'reschedule','due_at':(timezone.now()+timedelta(days=1)).isoformat(),'content':'延期'},format='json').status_code==200
    issue.refresh_from_db(); assert issue.overdue_recorded
    assert c.post(path,{'action':'transfer','department':dest.pk,'content':'移交'},format='json').status_code==200
    issue.refresh_from_db(); assert issue.department_id==dest.pk
    c.force_authenticate(users[2])
    assert c.post(path,{'action':'feedback','content':'反馈'},format='json').data['data']['first_feedback_at']
    assert c.post(path,{'action':'submit','content':'结果'},format='json').data['data']['confirmation_wait_seconds']>=0
    n=Notification.objects.filter(recipient=users[0]).first(); c.force_authenticate(users[2])
    c.post(base+'notifications/',{'id':n.pk},format='json'); n.refresh_from_db(); assert n.read_at is None
    c.force_authenticate(users[0]); c.post(base+'notifications/',{'id':n.pk},format='json'); n.refresh_from_db(); assert n.read_at

@pytest.mark.django_db
def test_pagination_history_and_retrieval_independent_of_filters():
    t=Tenant.objects.create(name='p',code='tracking-page'); d=Department.objects.create(tenant=t,name='dept')
    u=CustomUser.objects.create_user(username='page-u',tenant=t,user_type='internal')
    old=Issue.objects.create(tenant=t,creator=u,assignee=u,department=d,title='old open',due_at=timezone.now())
    Issue.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=100))
    closed=Issue.objects.create(tenant=t,creator=u,assignee=u,department=d,title='old closed',due_at=timezone.now(),status='closed',closed_at=timezone.now()-timedelta(days=40))
    c=APIClient(); c.force_authenticate(u); base='/api/internal/issue-tracking/issues/'
    r=c.get(base,{'status':'open','page_size':1}); assert r.data['data']['count']==1
    assert r.data['data']['results'][0]['id']==old.pk
    assert c.get(base,{'status':'closed'}).data['data']['count']==0
    assert c.get(base,{'status':'closed','all_history':'true'}).data['data']['count']==1
    assert c.get(base+str(old.pk)+'/',{'status':'closed','menu_key':'unrelated'}).status_code==200

@pytest.mark.django_db
def test_config_tenant_validation_and_partial_validity():
    t=Tenant.objects.create(name='cfg',code='tracking-config'); other=Tenant.objects.create(name='cfg2',code='tracking-config2')
    d=Department.objects.create(tenant=t,name='d'); od=Department.objects.create(tenant=other,name='od')
    admin=CustomUser.objects.create_user(username='cfg-admin',tenant=t,user_type='internal',is_superuser=True)
    u=CustomUser.objects.create_user(username='cfg-user',tenant=t,user_type='internal')
    c=APIClient(); c.force_authenticate(admin); base='/api/internal/issue-tracking/'
    assert c.post(base+'grants/',{'user':u.pk,'department':od.pk,'permissions':['view']},format='json').status_code==400
    assert c.post(base+'rules/',{'menu_key':'/test','candidate_departments':[od.pk]},format='json').status_code==400
    assert c.post(base+'rules/',{'menu_key':'/test','default_due_hours':0},format='json').status_code==400
    assert c.post(base+'rules/',{'menu_key':'/test','reminder_interval_minutes':0},format='json').status_code==400
    grant=ManagementGrant.objects.create(tenant=t,user=u,department=d,permissions=['view'],starts_at=timezone.now(),ends_at=timezone.now()+timedelta(days=1))
    assert c.patch(base+f'grants/{grant.pk}/',{'ends_at':(timezone.now()-timedelta(days=1)).isoformat()},format='json').status_code==400

@pytest.mark.django_db
def test_config_permission_revocation_and_attachment_revocation():
    from apps.permissions.models import Permission, Role, UserRole
    from apps.issue_tracking.models import ConfigurationAudit, Attachment
    t=Tenant.objects.create(name='r',code='tracking-revoke'); d=Department.objects.create(tenant=t,name='d')
    owner=CustomUser.objects.create_user(username='revoke-owner',tenant=t,user_type='internal')
    manager=CustomUser.objects.create_user(username='revoke-manager',tenant=t,user_type='internal')
    p=Permission.objects.get_or_create(code='issue_tracking.configure',defaults={'name':'配置','module':'issue_tracking','action':'configure'})[0]
    role=Role.objects.create(tenant=t,name='cfg',code='cfg'); role.permissions.add(p)
    binding=UserRole.objects.create(tenant=t,user=manager,role=role)
    c=APIClient(); c.force_authenticate(manager); base='/api/internal/issue-tracking/'
    r=c.post(base+'grants/',{'user':manager.pk,'department':d.pk,'permissions':['view']},format='json')
    assert r.status_code==201,r.data
    grant_id=r.data['data']['id']; assert ConfigurationAudit.objects.filter(actor=manager).exists()
    issue=Issue.objects.create(tenant=t,creator=owner,assignee=owner,department=d,title='secret',due_at=timezone.now())
    f=Attachment.objects.create(issue=issue,uploader=owner,name='x',content=b'x')
    assert c.get(base+f'attachments/{f.pk}/download/').status_code==200
    deleted=c.delete(base+f'grants/{grant_id}/')
    assert deleted.status_code==200 and deleted.data['success'] and deleted.data['data']['deleted']
    assert ConfigurationAudit.objects.filter(operation='delete',object_id=grant_id).exists()
    assert c.get(base+f'attachments/{f.pk}/download/').status_code==404
    binding.status='inactive'; binding.save()
    assert c.get(base+'grants/').status_code==403

@pytest.mark.django_db
def test_candidate_department_rules_create_and_reassign(monkeypatch):
    from apps.issue_tracking.models import MenuRule
    from apps.accounts.models import InternalUserProfile
    t=Tenant.objects.create(name='c',code='tracking-candidates'); d=Department.objects.create(tenant=t,name='yes'); other=Department.objects.create(tenant=t,name='no')
    users=[CustomUser.objects.create_user(username='candidate'+str(i),tenant=t,user_type='internal') for i in range(3)]
    InternalUserProfile.objects.create(user=users[1],tenant=t,department=d)
    InternalUserProfile.objects.create(user=users[2],tenant=t,department=other)
    rule=MenuRule.objects.create(tenant=t,menu_key='/test'); rule.candidate_departments.add(d)
    monkeypatch.setattr('apps.issue_tracking.links.validate_context',lambda *args,**kwargs:None)
    monkeypatch.setattr('apps.issue_tracking.links.can_access_page',lambda *args:True)
    c=APIClient(); c.force_authenticate(users[0]); base='/api/internal/issue-tracking/'
    assert [u['id'] for u in c.get(base+'candidates/',{'menu_key':'/test'}).data['data']['users']]==[users[1].pk]
    payload={'title':'candidate','department':d.pk,'assignee':users[2].pk,'menu_key':'/test','due_at':timezone.now().isoformat()}
    assert c.post(base+'issues/',payload,format='json').status_code==400
    payload['assignee']=users[1].pk
    r=c.post(base+'issues/',payload,format='json'); assert r.status_code==201,r.data
    ManagementGrant.objects.create(tenant=t,user=users[0],department=d,permissions=['view','reassign'])
    assert c.post(base+f"issues/{r.data['data']['id']}/actions/",{'action':'reassign','assignee':users[2].pk,'content':'改派'},format='json').status_code==400


@pytest.mark.django_db
def test_date_only_range_includes_entire_end_day():
    t=Tenant.objects.create(name='dates',code='tracking-dates'); d=Department.objects.create(tenant=t,name='dates')
    u=CustomUser.objects.create_user(username='dates-user',tenant=t,user_type='internal')
    ids=[]
    for stamp in ['2026-01-01T23:59:59+08:00','2026-01-02T00:00:00+08:00','2026-01-02T23:59:59+08:00','2026-01-03T00:00:00+08:00']:
        obj=Issue.objects.create(tenant=t,creator=u,assignee=u,department=d,title=stamp,due_at=timezone.now())
        from django.utils.dateparse import parse_datetime
        Issue.objects.filter(pk=obj.pk).update(created_at=parse_datetime(stamp)); ids.append(obj.pk)
    c=APIClient(); c.force_authenticate(u)
    with timezone.override('Asia/Shanghai'):
        r=c.get('/api/internal/issue-tracking/issues/',{'created_after':'2026-01-02','created_before':'2026-01-02'})
    assert r.status_code==200,r.data
    assert {row['id'] for row in r.data['data']['results']}==set(ids[1:3])

@pytest.mark.django_db
def test_menu_requires_existing_enabled_rule(monkeypatch):
    from apps.issue_tracking.models import MenuRule
    t=Tenant.objects.create(name='rules',code='tracking-real-rule'); d=Department.objects.create(tenant=t,name='rules')
    u=CustomUser.objects.create_user(username='rules-user',tenant=t,user_type='internal')
    monkeypatch.setattr('apps.issue_tracking.links.validate_context',lambda *args,**kwargs:None)
    c=APIClient(); c.force_authenticate(u)
    payload={'title':'rules','department':d.pk,'assignee':u.pk,'menu_key':'/configured','page_path':'/configured','due_at':timezone.now().isoformat()}
    path='/api/internal/issue-tracking/issues/'
    assert c.post(path,payload,format='json').status_code==400
    MenuRule.objects.create(tenant=t,menu_key='/configured',enabled=False)
    assert c.post(path,payload,format='json').status_code==400
