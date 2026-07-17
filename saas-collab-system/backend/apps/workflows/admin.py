from django.contrib import admin

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


admin.site.register((ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent))
