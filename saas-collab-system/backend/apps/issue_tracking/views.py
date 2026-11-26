from datetime import timedelta, datetime, time
from django.utils.dateparse import parse_date
from django.db import transaction
from django.db.models import Q, Prefetch
from apps.common.responses import success_response as Response
from apps.permissions.services import check_user_permission
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.contrib.auth import get_user_model
from rest_framework import viewsets, permissions, serializers
from rest_framework.decorators import action

from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.tenants.models import Department
from .models import *
from .serializers import *
from .access import visible, allowed, managed

class InternalOnly(permissions.BasePermission):
    def has_permission(self,request,view):
        return bool(request.user.is_authenticated and request.user.is_active and request.user.user_type=='internal')

class IssueViewSet(viewsets.GenericViewSet):
    permission_classes=[InternalOnly]
    serializer_class=IssueSerializer
    def get_queryset(self):
        metadata=Attachment.objects.only('id','issue_id','name','content_type','created_at')
        qs=visible(self.request.user).select_related('creator','assignee','department').prefetch_related('collaborators','events',Prefetch('attachments',queryset=metadata,to_attr='_attachment_metadata'))
        if self.action!='list': return qs
        p=self.request.query_params
        mode=p.get('view','')
        if mode=='created': qs=qs.filter(creator=self.request.user)
        if mode=='assigned': qs=qs.filter(assignee=self.request.user)
        if mode=='collaborating': qs=qs.filter(collaborators=self.request.user)
        if mode=='managed': qs=qs.filter(department_id__in=managed(self.request.user))
        for field in ['status','department','assignee','menu_key','record_id','record_type']:
            if field=='status' and p.get(field)=='open': qs=qs.exclude(status='closed')
            elif p.get(field): qs=qs.filter(**{field:p[field]})
        if p.get('search'): qs=qs.filter(Q(title__icontains=p['search'])|Q(description__icontains=p['search'])|Q(record_number__icontains=p['search']))
        for key,lookup in [('created_after','created_at__gte'),('created_before','created_at__lte'),('closed_after','closed_at__gte')]:
            if p.get(key):
                raw=p[key]
                day=parse_date(raw) if len(raw)==10 else None
                if day:
                    value=timezone.make_aware(datetime.combine(day,time.min))
                    if key=='created_before':
                        lookup='created_at__lt'; value+=timedelta(days=1)
                else:
                    value=parse_datetime(raw)
                if not value: raise ValidationError('日期筛选无效')
                if timezone.is_naive(value): value=timezone.make_aware(value)
                qs=qs.filter(**{lookup:value})
        if p.get('status')=='closed' and not p.get('all_history') and not p.get('closed_after'):
            qs=qs.filter(closed_at__gte=timezone.now()-timedelta(days=30))
        if p.get('overdue')=='true': qs=qs.filter(status__in=['pending','processing'],due_at__lt=timezone.now())
        return qs
    def validate_candidate(self,user,rule):
        if not rule or not rule.candidate_departments.exists(): return
        profile=getattr(user,'internal_profile',None)
        ids=set(rule.candidate_departments.values_list('pk',flat=True))
        if not profile or (profile.department_id not in ids and not profile.departments.filter(pk__in=ids).exists()): raise ValidationError('处理人不在候选范围')
    def list(self,request):
        from django.core.paginator import Paginator
        try:
            size=max(1,min(100,int(request.query_params.get('page_size',20))))
            page=max(1,int(request.query_params.get('page',1)))
        except (ValueError,TypeError): raise ValidationError('分页参数无效')
        paginator=Paginator(self.get_queryset(),size)
        result=paginator.get_page(page)
        return Response({'count':paginator.count,'results':self.get_serializer(result.object_list,many=True).data,'page':result.number,'page_size':size})
    def retrieve(self,request,pk=None): return Response(self.get_serializer(self.get_object()).data)
    @transaction.atomic
    def create(self,request):
        s=self.get_serializer(data=request.data); s.is_valid(raise_exception=True)
        from .links import validate_context
        validate_context(request.user,s.validated_data,assignee=s.validated_data['assignee'])
        rule=MenuRule.objects.filter(tenant_id=request.user.tenant_id,menu_key=s.validated_data.get('menu_key','')).first()
        if s.validated_data.get('menu_key') and not rule: raise ValidationError('此菜单尚未配置事项跟踪规则')
        if rule and not rule.enabled: raise ValidationError('此页面未启用事项跟踪')
        if rule and rule.scope=='record' and not s.validated_data.get('record_id'): raise ValidationError('此页面仅允许单据发起')
        if rule and rule.scope=='page' and s.validated_data.get('record_id'): raise ValidationError('此页面仅允许页面发起')
        if rule and rule.candidate_departments.exists():
            assignee=s.validated_data['assignee']
            self.validate_candidate(assignee,rule)
        for collaborator in s.validated_data.get('collaborators',[]):
            validate_context(request.user,s.validated_data,assignee=collaborator)
            self.validate_candidate(collaborator,rule)
        issue=s.save(tenant_id=request.user.tenant_id,creator=request.user)
        Event.objects.create(issue=issue,actor=request.user,action='create',content=issue.description)
        Notification.objects.create(issue=issue,recipient=issue.assignee,action='assigned')
        return Response(self.get_serializer(issue).data,status=201)
    @action(detail=True,methods=['post'],url_path='actions')
    @transaction.atomic
    def actions(self,request,pk=None):
        self.get_object()
        issue=Issue.objects.select_for_update().get(pk=pk)
        kind=request.data.get('action'); content=str(request.data.get('content','')).strip()
        if kind not in ['feedback','submit','return','close','reopen','reassign','reschedule','transfer','remind']: raise ValidationError('未知操作')
        if not allowed(request.user,issue,kind): raise PermissionDenied('没有操作权限')
        if not content and kind!='remind': raise ValidationError('请填写操作说明')
        now=timezone.now(); before={'status':issue.status,'due_at':issue.due_at.isoformat(),'assignee':issue.assignee_id,'department':issue.department_id}
        if issue.status=='closed' and kind!='reopen': raise ValidationError('事项已关闭')
        if kind=='reopen':
            if issue.status!='closed': raise ValidationError('仅可重开已关闭事项')
            issue.status='processing'; issue.closed_at=None
        elif kind=='feedback':
            if issue.status=='pending': issue.status='processing'
        elif kind=='submit':
            if issue.status not in ['pending','processing']: raise ValidationError('当前状态不可提交')
            issue.overdue_recorded |= issue.due_at<now; issue.status='confirming'; issue.submitted_at=now
        elif kind=='return':
            if issue.status!='confirming': raise ValidationError('仅可退回待确认事项')
            issue.status='processing'
        elif kind=='close':
            reason=request.data.get('close_reason','completed')
            if reason not in ['completed','cancelled','unnecessary']: raise ValidationError('关闭原因无效')
            if reason=='completed' and issue.status!='confirming': raise ValidationError('请先提交完成')
            issue.overdue_recorded |= issue.status in ['pending','processing'] and issue.due_at<now
            issue.status='closed'; issue.closed_at=now; issue.close_reason=reason
        elif kind=='reschedule':
            due=parse_datetime(str(request.data.get('due_at','')))
            if not due or timezone.is_naive(due): raise ValidationError('期限需包含时区')
            issue.overdue_recorded |= issue.status in ['pending','processing'] and issue.due_at<now
            issue.due_at=due
        elif kind=='reassign':
            user=get_user_model().objects.filter(pk=request.data.get('assignee'),tenant_id=request.user.tenant_id,is_active=True,user_type='internal').first()
            if not user: raise ValidationError('处理人无效')
            from .links import validate_context
            context={key:getattr(issue,key) for key in ['menu_key','page_path','record_type','record_id','record_number']}
            validate_context(request.user,context,assignee=user)
            self.validate_candidate(user,MenuRule.objects.filter(tenant_id=issue.tenant_id,menu_key=issue.menu_key).first())
            issue.assignee=user
        elif kind=='transfer':
            dept=Department.objects.filter(pk=request.data.get('department'),tenant_id=request.user.tenant_id,status='active').first()
            if not dept or dept.pk not in managed(request.user,'transfer'): raise PermissionDenied('缺少接收部门移交权限')
            issue.department=dept
        elif kind=='remind':
            if issue.status=='confirming': raise ValidationError('事项待确认，无需催办处理人')
            rule=MenuRule.objects.filter(tenant_id=issue.tenant_id,menu_key=issue.menu_key).first()
            interval=rule.reminder_interval_minutes if rule else 60
            if issue.last_reminded_at and now<issue.last_reminded_at+timedelta(minutes=interval): raise ValidationError('催办间隔未到')
            issue.last_reminded_at=now
        issue.save()
        Event.objects.create(issue=issue,actor=request.user,action=kind,content=content,data={'actor_role':('assignee' if request.user.pk==before['assignee'] else 'collaborator' if issue.collaborators.filter(pk=request.user.pk).exists() else 'creator' if request.user.pk==issue.creator_id else 'manager'),'before':before,'after':{'status':issue.status,'due_at':issue.due_at.isoformat(),'assignee':issue.assignee_id,'department':issue.department_id}})
        recipients={issue.creator_id,issue.assignee_id}- {request.user.pk}
        Notification.objects.bulk_create([Notification(issue=issue,recipient_id=uid,action=kind) for uid in recipients])
        return Response(self.get_serializer(issue).data)
    @action(detail=True,methods=['post'])
    def attachments(self,request,pk=None):
        issue=self.get_object()
        if request.user.pk not in {issue.creator_id,issue.assignee_id} and not issue.collaborators.filter(pk=request.user.pk).exists(): raise PermissionDenied('仅参与人可上传附件')
        upload=request.FILES.get('file')
        if not upload or upload.size>10*1024*1024: raise ValidationError('请选择不超过10MB的文件')
        content=upload.read()
        actual_image=False
        image_identified=False
        import re
        svg_signature=bool(re.match(rb'\s*(?:<\?xml[^>]*>\s*)?<svg(?:\s|>)',content[:4096],re.I))
        image_signature=(content.startswith(b'\x89PNG\r\n\x1a\n') or content.startswith(b'\xff\xd8\xff') or content.startswith((b'GIF87a',b'GIF89a')) or (len(content)>=12 and content[:4]==b'RIFF' and content[8:12]==b'WEBP') or content.startswith(b'BM'))
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(content)) as image:
                image_identified=True
                if image.format not in {'PNG','JPEG','GIF','WEBP','BMP'}: raise ValueError('unsupported')
                image.verify(); actual_image=True
        except Exception:
            if image_identified or image_signature or svg_signature or (upload.content_type or '').startswith('image/') or upload.name.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg','.tif','.tiff')):
                raise ValidationError('图片文件无效')
        rule=MenuRule.objects.filter(tenant_id=issue.tenant_id,menu_key=issue.menu_key).first()
        if actual_image and rule and not rule.screenshot_enabled: raise ValidationError('此页面不允许截图附件')
        with transaction.atomic():
            locked=Issue.objects.select_for_update().get(pk=issue.pk)
            if locked.status=='closed': raise ValidationError('事项已关闭')
            if request.user.pk not in {locked.creator_id,locked.assignee_id} and not locked.collaborators.filter(pk=request.user.pk).exists(): raise PermissionDenied('仅参与人可上传附件')
            if Attachment.objects.filter(issue=locked).count()>=20: raise ValidationError('每个事项最多上传20个附件')
            obj=Attachment.objects.create(issue=locked,uploader=request.user,name=upload.name,content=content,content_type=upload.content_type or 'application/octet-stream')
            Event.objects.create(issue=locked,actor=request.user,action='attachment',content=obj.name)
        return Response({'id':obj.pk,'name':obj.name},status=201)

class ConfigViewSet(viewsets.ModelViewSet):
    def finalize_response(self,request,response,*args,**kwargs):
        if response.status_code<400 and not (isinstance(response.data,dict) and 'success' in response.data):
            response.data={'success':True,'code':'OK','message':'success','data':response.data}
        return super().finalize_response(request,response,*args,**kwargs)
    permission_classes=[InternalOnly]
    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if not (request.user.is_superuser or check_user_permission(request.user, 'issue_tracking.configure')): raise PermissionDenied('需要管理员权限')
    def get_queryset(self): return self.queryset.filter(tenant_id=self.request.user.tenant_id)
    def audit(self,obj,operation):
        ConfigurationAudit.objects.create(tenant_id=self.request.user.tenant_id,actor=self.request.user,kind=obj.__class__.__name__,object_id=obj.pk,operation=operation,data=self.get_serializer(obj).data)
    @transaction.atomic
    def perform_create(self,serializer):
        obj=serializer.save(tenant_id=self.request.user.tenant_id); self.audit(obj,'create')
    @transaction.atomic
    def perform_update(self,serializer):
        self.audit(serializer.instance,'before_update')
        obj=serializer.save(); self.audit(obj,'update')
    def destroy(self,request,*args,**kwargs):
        instance=self.get_object()
        self.perform_destroy(instance)
        return Response({'deleted':True})
    @transaction.atomic
    def perform_destroy(self,instance):
        self.audit(instance,'delete'); instance.delete()
class GrantViewSet(ConfigViewSet):
    queryset=ManagementGrant.objects.all(); serializer_class=GrantSerializer
class RuleViewSet(ConfigViewSet):
    queryset=MenuRule.objects.all(); serializer_class=RuleSerializer

from rest_framework.views import APIView
class Candidates(APIView):
    def user_departments(self,user):
        profile=getattr(user,'internal_profile',None)
        if not profile: return []
        return sorted(set(profile.departments.values_list('pk',flat=True))|({profile.department_id} if profile.department_id else set()))
    permission_classes=[InternalOnly]
    def get(self,request):
        users=get_user_model().objects.filter(tenant_id=request.user.tenant_id,is_active=True,user_type='internal')
        from .links import can_access_page, can_access_record
        menu=request.query_params.get('menu_key','')
        if menu or request.query_params.get('record_type') or request.query_params.get('record_id'):
            from .links import validate_context
            validate_context(request.user, {'menu_key':menu,'page_path':menu,'record_type':request.query_params.get('record_type',''),'record_id':request.query_params.get('record_id','')})
        rule=MenuRule.objects.filter(tenant_id=request.user.tenant_id,menu_key=menu).first()
        if rule and rule.candidate_departments.exists():
            ids=rule.candidate_departments.values('pk')
            users=users.filter(Q(internal_profile__department_id__in=ids)|Q(internal_profile__departments__in=ids)).distinct()
        kind=request.query_params.get('record_type',''); identity=request.query_params.get('record_id','')
        candidates=[u for u in users if (not menu or can_access_page(u,menu)) and (not (kind or identity) or can_access_record(u,kind,identity))]
        return Response({'users':[{'id':u.pk,'username':u.username,'full_name':u.full_name,'department_ids':self.user_departments(u)} for u in candidates],'can_manage':bool(managed(request.user)),'can_configure':request.user.is_superuser or check_user_permission(request.user,'issue_tracking.configure'),'departments':list(Department.objects.filter(tenant_id=request.user.tenant_id,status='active').values('id','name','parent')),'rules':RuleSerializer(MenuRule.objects.filter(tenant_id=request.user.tenant_id),many=True).data})
class Summary(APIView):
    permission_classes=[InternalOnly]
    def get(self,request):
        qs=visible(request.user)
        return Response({'pending':qs.filter(status='pending').count(),'processing':qs.filter(status='processing').count(),'confirming':qs.filter(status='confirming').count(),'overdue':qs.filter(status__in=['pending','processing'],due_at__lt=timezone.now()).count(),'items':IssueSerializer(qs.exclude(status='closed')[:5],many=True,context={'request':request}).data})
class Notifications(APIView):
    permission_classes=[InternalOnly]
    def get(self,request): return Response(list(Notification.objects.filter(recipient=request.user,issue__tenant_id=request.user.tenant_id,issue__in=visible(request.user)).order_by('-created_at').values('id','issue','action','read_at','created_at')[:100]))
    def post(self,request):
        Notification.objects.filter(recipient=request.user,pk=request.data.get('id')).update(read_at=timezone.now())
        return Response({'ok':True})
class Download(APIView):
    permission_classes=[InternalOnly]
    def get(self,request,pk):
        from django.shortcuts import get_object_or_404
        obj=get_object_or_404(Attachment,pk=pk,issue__in=visible(request.user))
        response=HttpResponse(bytes(obj.content),content_type='application/octet-stream')
        from django.utils.http import content_disposition_header
        response['Content-Disposition']=content_disposition_header(True,obj.name)
        response['X-Content-Type-Options']='nosniff'
        return response
