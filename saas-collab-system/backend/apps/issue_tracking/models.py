from django.conf import settings
from django.db import models

class Issue(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_tracking_issues')
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_tracking_issues')
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='collaborating_tracking_issues')
    department = models.ForeignKey('tenants.Department', on_delete=models.PROTECT)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending', choices=[('pending','待办理'),('processing','办理中'),('confirming','待确认'),('closed','已关闭')])
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True)
    closed_at = models.DateTimeField(null=True)
    last_reminded_at = models.DateTimeField(null=True)
    overdue_recorded = models.BooleanField(default=False)
    close_reason = models.CharField(max_length=30, blank=True)
    menu_key = models.CharField(max_length=200, blank=True)
    page_path = models.CharField(max_length=500, blank=True)
    record_type = models.CharField(max_length=100, blank=True)
    record_id = models.CharField(max_length=100, blank=True)
    record_number = models.CharField(max_length=100, blank=True)
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['tenant','status','due_at'])]

class Event(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    content = models.TextField(blank=True)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at','id']

class ManagementGrant(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    department = models.ForeignKey('tenants.Department', on_delete=models.CASCADE)
    include_descendants = models.BooleanField(default=False)
    permissions = models.JSONField(default=list)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class MenuRule(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    menu_key = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)
    screenshot_enabled = models.BooleanField(default=True)
    scope = models.CharField(max_length=10,default='both',choices=[('page','页面'),('record','单据'),('both','页面和单据')])
    default_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    candidate_departments = models.ManyToManyField('tenants.Department', blank=True)
    default_due_hours = models.PositiveIntegerField(default=48)
    reminder_interval_minutes = models.PositiveIntegerField(default=60)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['tenant','menu_key'],name='tracking_unique_menu_rule')]

class Notification(models.Model):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracking_notifications")
    action = models.CharField(max_length=30)
    read_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Attachment(models.Model):
    issue = models.ForeignKey(Issue,on_delete=models.CASCADE,related_name='attachments')
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    name = models.CharField(max_length=255)
    content = models.BinaryField()
    content_type = models.CharField(max_length=100, default='application/octet-stream')
    created_at = models.DateTimeField(auto_now_add=True)


class ConfigurationAudit(models.Model):
    tenant = models.ForeignKey('tenants.Tenant',on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    kind = models.CharField(max_length=30)
    object_id = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=20)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
