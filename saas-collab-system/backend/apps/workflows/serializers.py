from rest_framework import serializers

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


class WorkflowAuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowAuditEvent
        fields = ("id", "action", "actor_id", "from_status", "to_status", "masked_detail", "created_at")
        read_only_fields = fields


class ApprovalRequestSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    audit_events = serializers.SerializerMethodField()
    business_link = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = (
            "id", "tenant_id", "approval_type", "title", "business_type", "business_id", "status",
            "requested_by_id", "reviewed_by_id", "reason", "decision_note", "idempotency_key",
            "created_at", "updated_at", "decided_at", "audit_events", "business_link",
        )
        read_only_fields = fields

    def get_audit_events(self, obj):
        page_events = self.context.get("audit_events_by_resource")
        if page_events is not None:
            return WorkflowAuditEventSerializer(page_events.get(str(obj.id), []), many=True).data
        events = WorkflowAuditEvent.objects.filter(tenant=obj.tenant, resource_type="approval", resource_id=str(obj.id))
        return WorkflowAuditEventSerializer(events, many=True).data

    def get_business_link(self, obj):
        if obj.business_type == "supply_payment_batch":
            from apps.supply_chain.payment_batches import visible_batches
            request = self.context.get("request")
            if request is None:
                return ""
            batch_id=visible_batches(request.user).filter(approval=obj).values_list('pk',flat=True).first()
            return f"/supply-chain/costs?tab=reconciliation&payment_batch_id={batch_id}" if batch_id else ""
        if obj.business_type != "supply_payment_request":
            return ""
        rows = self.context.get("payment_requests_by_approval")
        if rows is not None:
            row = rows.get(obj.pk)
        else:
            from apps.supply_chain.payment_request_models import SupplyPaymentRequest
            row = SupplyPaymentRequest.objects.filter(tenant_id=obj.tenant_id, approval=obj).first()
        if row is None:
            return ""
        # The paginated mapping is built only after visible_approvals applies source scope in SQL.
        if rows is None:
            from apps.supply_chain.costs import _payment_owner
            try:
                _payment_owner(self.context.get("request").user, row.kind, row.source_id, "supply.v2.view")
            except Exception:
                return ""
        return f"/supply-chain/costs?kind={row.kind}&id={row.source_id}&payment_request_id={row.pk}"


class ApprovalMockCreateSerializer(serializers.Serializer):
    approval_type = serializers.ChoiceField(choices=ApprovalRequest.ApprovalType.choices)
    title = serializers.CharField(max_length=200)
    business_type = serializers.CharField(max_length=80)
    business_id = serializers.CharField(max_length=100)
    reason = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=120)


class DecisionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class BusinessExceptionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    audit_events = serializers.SerializerMethodField()

    class Meta:
        model = BusinessException
        fields = (
            "id", "tenant_id", "module", "title", "severity", "status", "business_type", "business_id",
            "assigned_to_id", "created_by_id", "description", "resolution", "created_at", "updated_at",
            "resolved_at", "closed_at", "audit_events",
        )
        read_only_fields = fields

    def get_audit_events(self, obj):
        page_events = self.context.get("audit_events_by_resource")
        if page_events is not None:
            return WorkflowAuditEventSerializer(page_events.get(str(obj.id), []), many=True).data
        events = WorkflowAuditEvent.objects.filter(tenant=obj.tenant, resource_type="exception", resource_id=str(obj.id))
        return WorkflowAuditEventSerializer(events, many=True).data


class ExceptionMockCreateSerializer(serializers.Serializer):
    module = serializers.ChoiceField(choices=BusinessException.Module.choices)
    title = serializers.CharField(max_length=200)
    severity = serializers.ChoiceField(choices=BusinessException.Severity.choices, default=BusinessException.Severity.MEDIUM)
    business_type = serializers.CharField(max_length=80, required=False, allow_blank=True)
    business_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)


class AssignSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField()


class ResolutionSerializer(serializers.Serializer):
    resolution = serializers.CharField(max_length=2000)


class CollaborationEventSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    audit_events = serializers.SerializerMethodField()

    class Meta:
        model = CollaborationEvent
        fields = (
            "id", "tenant_id", "channel", "event_id", "event_type", "payload_hash", "masked_summary",
            "status", "confirmed_by_id", "decision_note", "received_at", "processed_at", "audit_events",
        )
        read_only_fields = fields

    def get_audit_events(self, obj):
        page_events = self.context.get("audit_events_by_resource")
        if page_events is not None:
            return WorkflowAuditEventSerializer(page_events.get(str(obj.id), []), many=True).data
        events = WorkflowAuditEvent.objects.filter(tenant=obj.tenant, resource_type="collaboration", resource_id=str(obj.id))
        return WorkflowAuditEventSerializer(events, many=True).data


class PaginationQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class ApprovalQuerySerializer(PaginationQuerySerializer):
    approval_type = serializers.ChoiceField(choices=ApprovalRequest.ApprovalType.choices, required=False)
    status = serializers.ChoiceField(choices=ApprovalRequest.Status.choices, required=False)


class ExceptionQuerySerializer(PaginationQuerySerializer):
    module = serializers.ChoiceField(choices=BusinessException.Module.choices, required=False)
    status = serializers.ChoiceField(choices=BusinessException.Status.choices, required=False)


class CollaborationQuerySerializer(PaginationQuerySerializer):
    channel = serializers.ChoiceField(choices=CollaborationEvent.Channel.choices, required=False)
    status = serializers.ChoiceField(choices=CollaborationEvent.Status.choices, required=False)
