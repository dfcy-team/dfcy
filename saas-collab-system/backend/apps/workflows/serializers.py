from rest_framework import serializers
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone

from .models import ApprovalRequest, BusinessException, CollaborationEvent, WorkflowAuditEvent


class WorkflowAuditEventSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()
    from_status = serializers.SerializerMethodField()
    to_status = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    class Meta:
        model = WorkflowAuditEvent
        fields = ("id", "action", "actor_id", "from_status", "to_status", "masked_detail", "created_at")
        read_only_fields = fields

    def get_action(self, obj):
        return {"submit": "提交", "approve": "通过", "reject": "驳回", "withdraw": "撤回", "submit_mock": "提交"}.get(obj.action, "其他操作")

    def get_from_status(self, obj):
        return {"pending": "待审批", "approved": "已通过", "rejected": "已驳回", "withdrawn": "已撤回", "": "—"}.get(obj.from_status, "其他状态")

    def get_to_status(self, obj):
        return {"pending": "待审批", "approved": "已通过", "rejected": "已驳回", "withdrawn": "已撤回", "": "—"}.get(obj.to_status, "其他状态")

    def get_created_at(self, obj):
        return timezone.localtime(obj.created_at, ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))).isoformat()


class ApprovalRequestSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    audit_events = serializers.SerializerMethodField()
    business_link = serializers.SerializerMethodField()
    payment_context = serializers.SerializerMethodField()
    payment_display = serializers.SerializerMethodField()
    business_reference = serializers.SerializerMethodField()
    requested_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    designated_reviewer_name = serializers.SerializerMethodField()
    workflow_snapshot = serializers.JSONField(read_only=True)
    approval_type_label = serializers.SerializerMethodField()
    business_type_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    decided_at = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    updated_at = serializers.SerializerMethodField()
    decided_at = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = (
            "id", "tenant_id", "approval_type", "approval_type_label", "title", "business_type", "business_type_label", "business_id", "business_reference", "status", "status_label",
            "requested_by_id", "requested_by_name", "reviewed_by_id", "reviewed_by_name", "designated_reviewer_id", "designated_reviewer_name", "workflow_snapshot", "reason", "decision_note", "idempotency_key",
            "created_at", "updated_at", "decided_at", "audit_events", "business_link", "payment_context", "payment_display",
        )
        read_only_fields = fields

    def get_requested_by_name(self, obj):
        return obj.requested_by.full_name or "姓名未维护"

    def get_reviewed_by_name(self, obj):
        return (obj.reviewed_by.full_name or "姓名未维护") if obj.reviewed_by else ""

    def get_designated_reviewer_name(self, obj):
        return (obj.designated_reviewer.full_name or "姓名未维护") if obj.designated_reviewer else ""

    def get_approval_type_label(self, obj):
        return {"purchase":"采购审批", "price":"价格审批", "listing":"刊登审批", "clearance":"清仓审批", "finance":"财务审批", "report_export":"报表导出"}.get(obj.approval_type, "其他审批类型")

    def get_business_type_label(self, obj):
        if obj.business_type == "supply_payment_request":
            row = self._payment_request(obj)
            if row:
                return self._payment_kind_label(row.kind) + "申请"
            return "供应商付款申请"
        return {"supply_payment_batch":"合并付款申请"}.get(obj.business_type, "其他业务")

    def _payment_kind_label(self, kind):
        return {"purchase":"采购定金", "shipment":"供应商货款", "domestic_freight":"国内运费",
                "batch":"国际/批次货运费", "inbound":"入库费用"}.get(kind, "付款")

    def _payment_request(self, obj):
        rows = self.context.get("payment_requests_by_approval")
        if rows is not None:
            return rows.get(obj.pk)
        from apps.supply_chain.payment_request_models import SupplyPaymentRequest
        return SupplyPaymentRequest.objects.filter(tenant_id=obj.tenant_id, approval_id=obj.pk).select_related("payee_account").first()

    def _payment_batch(self, obj, user):
        from apps.supply_chain.payment_batches import visible_batches
        return visible_batches(user).filter(approval_id=obj.pk).prefetch_related("lines").first()

    def get_business_reference(self, obj):
        request = self.context.get("request")
        if request is None:
            return self.get_business_type_label(obj) if obj.business_type in {"supply_payment_request", "supply_payment_batch"} else obj.title
        try:
            if obj.business_type == "supply_payment_request":
                row = self._payment_request(obj)
                if not row:
                    return ""
                from apps.supply_chain.costs import _payment_owner
                source = _payment_owner(request.user, row.kind, row.source_id, "supply.v2.view")
                return source.number
            if obj.business_type == "supply_payment_batch":
                batch = self._payment_batch(obj, request.user)
                if not batch:
                    return ""
                from apps.supply_chain.costs import _payment_owner
                numbers = [_payment_owner(request.user, line.kind, line.source_id, "supply.v2.view").number for line in batch.lines.all()]
                return "、".join(numbers)
        except Exception:
            return ""
        return obj.title

    def get_payment_display(self, obj):
        request = self.context.get("request")
        if request is None:
            return None
        tail = lambda snapshot: str(snapshot.get("account_number", ""))[-4:]
        if obj.business_type == "supply_payment_request":
            row = self._payment_request(obj)
            if not row:
                return None
            return {"application_reference": f"付款申请记录（系统序号 {row.pk}）", "amount": str(row.amount),
                "payment_type": self._payment_kind_label(row.kind), "payment_object": row.account_snapshot.get("account_holder") or row.account_snapshot.get("account_name", ""),
                "nature": "对私" if row.account_snapshot.get("nature") == "personal" else "对公",
                "account_tail": tail(row.account_snapshot), "reason": row.reason}
        if obj.business_type == "supply_payment_batch":
            batch = self._payment_batch(obj, request.user)
            if not batch:
                return None
            amount = sum((line.amount for line in batch.lines.all()), start=0)
            kinds = sorted({self._payment_kind_label(line.kind) for line in batch.lines.all()})
            return {"application_reference": f"合并付款记录（系统序号 {batch.pk}）", "amount": str(amount),
                "payment_type": "、".join(kinds), "payment_object": batch.account_snapshot.get("account_holder") or batch.account_snapshot.get("account_name", ""),
                "nature": "对私" if batch.account_snapshot.get("nature") == "personal" else "对公",
                "account_tail": tail(batch.account_snapshot), "reason": batch.reason}
        return None

    def get_status_label(self, obj):
        return {"pending":"待审批", "approved":"已通过", "rejected":"已驳回", "withdrawn":"已撤回"}.get(obj.status, "其他状态")

    def _china_time(self, value):
        if not value: return None
        return timezone.localtime(value, ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))).isoformat()

    def get_created_at(self, obj): return self._china_time(obj.created_at)
    def get_updated_at(self, obj): return self._china_time(obj.updated_at)
    def get_decided_at(self, obj): return self._china_time(obj.decided_at)

    def _china_time(self, value):
        if not value: return None
        return timezone.localtime(value, ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))).isoformat()

    def get_created_at(self, obj): return self._china_time(obj.created_at)
    def get_updated_at(self, obj): return self._china_time(obj.updated_at)
    def get_decided_at(self, obj): return self._china_time(obj.decided_at)

    def get_payment_context(self, obj):
        request = self.context.get('request')
        if request is None or obj.business_type not in ('supply_payment_request', 'supply_payment_batch'):
            return None
        # Detail only: avoid extra attachment/source queries on paginated approval lists.
        if 'audit_events_by_resource' in self.context:
            return None
        from apps.supply_chain.payment_requests import request_data, finance_allowed
        from apps.supply_chain.payment_request_models import SupplyPaymentRequest
        from apps.supply_chain.costs import _payment_owner
        if obj.business_type == 'supply_payment_request':
            row = SupplyPaymentRequest.objects.filter(tenant_id=obj.tenant_id, approval=obj).first()
            if row is None:
                return None
            _payment_owner(request.user, row.kind, row.source_id, 'supply.v2.view')
            data = request_data(request.user, row)
            identity = dict(mode='single', kind=row.kind, source_id=row.source_id, request_id=row.pk, batch_id=None)
        else:
            from apps.supply_chain.payment_batches import visible_batches, _data
            row = visible_batches(request.user).filter(approval=obj).first()
            if row is None:
                return None
            data = _data(request.user, row)
            identity = dict(mode='batch', kind=None, source_id=None, request_id=None, batch_id=row.pk)
        if data['can_upload']:
            from rest_framework.exceptions import APIException
            sources = [(row.kind, row.source_id)] if identity['mode'] == 'single' else [(line.kind, line.source_id) for line in row.lines.all()]
            try:
                for kind, source_id in sources:
                    _payment_owner(request.user, kind, source_id, 'supply.v2.manage')
            except APIException:
                data['can_upload'] = False
        return {**identity, **{key: data[key] for key in ('version', 'amount', 'vouchers', 'can_upload', 'account_snapshot', 'status')},
                'can_post': bool(data['can_upload'] and finance_allowed(request.user))}

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
    payment = serializers.DictField(required=False)
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
