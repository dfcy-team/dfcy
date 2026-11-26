from django.db.models import Q
from django.utils import timezone
from .models import ManagementGrant, Issue

def department_ids(grant):
    ids = {grant.department_id}
    if grant.include_descendants:
        from apps.tenants.models import Department
        while True:
            extra = set(Department.objects.filter(tenant_id=grant.tenant_id,parent_id__in=ids).values_list('id',flat=True)) - ids
            if not extra: break
            ids |= extra
    return ids

def grants(user):
    now = timezone.now()
    return ManagementGrant.objects.filter(tenant_id=user.tenant_id,user=user).filter(Q(starts_at__isnull=True)|Q(starts_at__lte=now)).filter(Q(ends_at__isnull=True)|Q(ends_at__gt=now))

def managed(user, permission='view'):
    ids=set()
    for grant in grants(user):
        if permission in grant.permissions: ids |= department_ids(grant)
    return ids

def visible(user):
    return Issue.objects.filter(tenant_id=user.tenant_id).filter(Q(creator=user)|Q(assignee=user)|Q(collaborators=user)|Q(department_id__in=managed(user))).distinct()

def allowed(user, issue, action):
    if action=='view': return visible(user).filter(pk=issue.pk).exists()
    if action=='feedback': return user.pk in {issue.creator_id,issue.assignee_id} or issue.collaborators.filter(pk=user.pk).exists()
    if action=='submit': return issue.assignee_id==user.pk
    if action in ('close','return','reopen','reschedule','remind'): return issue.creator_id==user.pk or issue.department_id in managed(user,action)
    return issue.department_id in managed(user,action)
