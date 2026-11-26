from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.tenants.models import Department
from .models import *

class IssueSerializer(serializers.ModelSerializer):
    events = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    first_feedback_at = serializers.SerializerMethodField()
    last_feedback_at = serializers.SerializerMethodField()
    confirmation_wait_seconds = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        request=self.context.get('request')
        tenant=getattr(getattr(request,'user',None),'tenant_id',None)
        if not tenant:
            self.fields['assignee'].queryset=self.fields['assignee'].queryset.none()
            self.fields['collaborators'].child_relation.queryset=self.fields['collaborators'].child_relation.queryset.none()
            self.fields['department'].queryset=self.fields['department'].queryset.none()
        else:
            users=get_user_model().objects.filter(tenant_id=tenant,is_active=True,user_type='internal')
            self.fields['assignee'].queryset=users
            self.fields['collaborators'].child_relation.queryset=users
            self.fields['department'].queryset=Department.objects.filter(tenant_id=tenant,status='active')
    def get_first_feedback_at(self,obj):
        row=obj.events.filter(action='feedback',data__actor_role__in=['assignee','collaborator']).first()
        return row.created_at if row else None
    def get_last_feedback_at(self,obj):
        row=obj.events.filter(action='feedback',data__actor_role__in=['assignee','collaborator']).last()
        return row.created_at if row else None
    def get_confirmation_wait_seconds(self,obj):
        from django.utils import timezone
        return max(0,int((timezone.now()-obj.submitted_at).total_seconds())) if obj.status=='confirming' and obj.submitted_at else 0
    def get_is_overdue(self,obj):
        from django.utils import timezone
        return obj.status in ['pending','processing'] and obj.due_at<timezone.now()
    class Meta:
        model=Issue
        fields='__all__'
        read_only_fields=['tenant','creator','status','submitted_at','closed_at','last_reminded_at','overdue_recorded','close_reason']
    def get_events(self,obj):
        return list(obj.events.values('id','actor','action','content','data','created_at'))
    def get_attachments(self,obj):
        rows=getattr(obj,'_attachment_metadata',None)
        if rows is None: rows=obj.attachments.only('id','name','content_type','created_at').all()
        return [{'id':a.pk,'name':a.name,'content_type':a.content_type,'created_at':a.created_at} for a in rows]
    def get_permissions(self,obj):
        from .access import allowed
        actions=['reopen'] if obj.status=='closed' else ['feedback','close','reassign','reschedule','transfer']
        if obj.status in ['pending','processing']: actions+=['submit','remind']
        if obj.status=='confirming': actions+=['return']
        return [a for a in actions if allowed(self.context['request'].user,obj,a)]
    def validate(self,data):
        user=self.context['request'].user
        for key in ['assignee']:
            if key in data and (data[key].tenant_id!=user.tenant_id or not data[key].is_active or data[key].user_type!='internal'): raise serializers.ValidationError({key:'请选择本租户在职用户'})
        if 'due_at' in data and __import__('django.utils.timezone',fromlist=['is_naive']).is_naive(data['due_at']): raise serializers.ValidationError({'due_at':'请提供有效时区'})
        if 'department' in data and (data['department'].tenant_id!=user.tenant_id or data['department'].status!='active'): raise serializers.ValidationError({'department':'部门不属于当前租户'})
        if any(u.tenant_id!=user.tenant_id or not u.is_active or u.user_type!='internal' for u in data.get('collaborators',[])): raise serializers.ValidationError({'collaborators':'协办人无效'})
        path=data.get('page_path','')
        if path and (not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path): raise serializers.ValidationError({'page_path':'仅支持无参数的站内路径'})
        return data

class GrantSerializer(serializers.ModelSerializer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); request=self.context.get('request'); tenant=getattr(getattr(request,'user',None),'tenant_id',None)
        self.fields['user'].queryset=get_user_model().objects.filter(tenant_id=tenant,is_active=True,user_type='internal') if tenant else get_user_model().objects.none()
        self.fields['department'].queryset=Department.objects.filter(tenant_id=tenant,status='active') if tenant else Department.objects.none()
    class Meta:
        model=ManagementGrant
        fields='__all__'
        read_only_fields=['tenant']
    def validate(self,data):
        tenant=self.context['request'].user.tenant_id
        if any(data[k].tenant_id!=tenant for k in ['user','department'] if k in data): raise serializers.ValidationError('不能跨租户授权')
        valid={'view','remind','reassign','reschedule','close','reopen','return','transfer'}
        if any(p not in valid for p in data.get('permissions',[])): raise serializers.ValidationError('权限码无效')
        start=data.get('starts_at',getattr(self.instance,'starts_at',None))
        end=data.get('ends_at',getattr(self.instance,'ends_at',None))
        if start and end and start>=end: raise serializers.ValidationError('有效期错误')
        return data

class RuleSerializer(serializers.ModelSerializer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); request=self.context.get('request'); tenant=getattr(getattr(request,'user',None),'tenant_id',None)
        self.fields['default_assignee'].queryset=get_user_model().objects.filter(tenant_id=tenant,is_active=True,user_type='internal') if tenant else get_user_model().objects.none()
        self.fields['candidate_departments'].child_relation.queryset=Department.objects.filter(tenant_id=tenant,status='active') if tenant else Department.objects.none()
    class Meta:
        model=MenuRule
        fields='__all__'
        read_only_fields=['tenant']
    def validate(self,data):
        tenant=self.context['request'].user.tenant_id
        for key in ['default_due_hours','reminder_interval_minutes']:
            if key in data and data[key]<1: raise serializers.ValidationError({key:'必须大于0'})
        if data.get('default_assignee') and data['default_assignee'].tenant_id!=tenant: raise serializers.ValidationError('默认处理人跨租户')
        if any(d.tenant_id!=tenant for d in data.get('candidate_departments',[])): raise serializers.ValidationError('候选部门跨租户')
        return data
