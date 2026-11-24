"""Durable native approval submission. External calls run after business commit."""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import FeishuApprovalMapping, FeishuApprovalInstance, FeishuConnection, FeishuIdentity, FeishuApprovalEvent
from .feishu_native_client import FeishuNativeClient, FeishuNativeAPIError

BUSINESS_TYPES = {'supply_payment_request', 'supply_payment_batch'}


def definition_hash(definition):
    pinned = {key: definition.get(key) for key in ('approval_code', 'status', 'form', 'node_list')}
    return hashlib.sha256(json.dumps(pinned, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _connection(tenant_id):
    connection = FeishuConnection.objects.filter(tenant_id=tenant_id, enabled=True).first()
    if not connection or not connection.verification_token_ref or not connection.encrypt_key_ref:
        raise ValidationError('飞书审批回调密钥尚未配置。')
    return connection


def _identity(user):
    identity = FeishuIdentity.objects.filter(tenant_id=user.tenant_id, user=user, status='active', user__is_active=True, user__user_type='internal').exclude(open_id='').first()
    if not identity:
        raise ValidationError('审批申请人或审批人尚未绑定有效飞书身份。')
    return identity.open_id


def queue_payment_approval(approval, row, *, form_input=None):
    """Return None for an unmapped flow; an enabled mapping fails closed."""
    mapping = FeishuApprovalMapping.objects.filter(tenant_id=approval.tenant_id,
        flow_key=approval.workflow_snapshot.get('flow_key', ''), business_type=approval.business_type, enabled=True).first()
    if mapping is None:
        if FeishuApprovalMapping.objects.filter(tenant_id=approval.tenant_id, business_type=approval.business_type, enabled=True).exists():
            raise ValidationError('此付款流程尚未匹配飞书审批模板，请联系管理员。')
        return None
    if approval.business_type not in BUSINESS_TYPES or row.tenant_id != approval.tenant_id or row.approval_id != approval.pk:
        raise ValidationError('付款来源与审批关联不一致。')
    if not mapping.fixed_assignees_verified or not mapping.subscription_verified:
        raise ValidationError('飞书审批人员及事件订阅尚未核验。')
    connection = _connection(approval.tenant_id)
    if mapping.reviewer_id != approval.designated_reviewer_id or mapping.reviewer_open_id != _identity(approval.designated_reviewer):
        raise ValidationError('系统流程审批人与飞书模板审批人不匹配。')
    if mapping.definition_hash != definition_hash(mapping.definition):
        raise ValidationError('飞书审批模板快照已变化，请重新核验。')
    if not isinstance(form_input, dict):
        raise ValidationError({'feishu': '请填写付款类型、付款方式和计划付款日期。'})
    if set(form_input) != {'payment_type', 'payment_method', 'payment_date'}:
        raise ValidationError({'feishu': '须且仅须提供付款类型、付款方式和计划付款日期。'})
    from .feishu_payment_form import build_payment_form
    if approval.business_type == 'supply_payment_batch':
        lines = list(row.lines.all())
        if not lines or any(line.currency != row.currency for line in lines):
            raise ValidationError('付款批次来源币种不一致。')
        amount = sum((line.amount for line in lines), Decimal(0))
    else:
        amount = row.amount
    form = build_payment_form(mapping.definition, reason=row.reason, amount=amount,
        currency=row.currency, account_snapshot=row.account_snapshot, **form_input)
    finance_snapshot = {}
    handler_id = approval.workflow_snapshot.get('finance_handler_id')
    if (mapping.finance_node_id or mapping.finance_date_widget_id or mapping.finance_voucher_widget_id) and not handler_id:
        raise ValidationError('此飞书付款流程要求配置独立财务办理人。')
    if handler_id:
        from apps.accounts.models import CustomUser
        handler = CustomUser.objects.filter(pk=handler_id, tenant_id=approval.tenant_id, is_active=True, user_type='internal').first()
        if not handler:
            raise ValidationError('财务办理人无效。')
        required = [mapping.finance_node_id, mapping.finance_date_widget_id, mapping.finance_voucher_widget_id, mapping.finance_attachment_hosts]
        if not all(required):
            raise ValidationError('飞书财务办理节点、日期、凭证和下载主机尚未配置完整。')
        widgets = mapping.definition.get('form', [])
        if isinstance(widgets, str):widgets=json.loads(widgets)
        by_id={w.get('id'):w for w in widgets}
        if (by_id.get(mapping.finance_date_widget_id,{}).get('type') != 'date' or
                by_id.get(mapping.finance_voucher_widget_id,{}).get('type') not in ('attachmentV2','attachment','image','imageV2')):
            raise ValidationError('飞书财务字段类型不匹配。')
        finance_snapshot={'handler_id':handler.pk,'handler_open_id':_identity(handler),'node_id':mapping.finance_node_id,
            'date_widget_id':mapping.finance_date_widget_id,'voucher_widget_id':mapping.finance_voucher_widget_id,
            'attachment_hosts':mapping.finance_attachment_hosts}
    sender = _identity(approval.requested_by)
    defaults = {'tenant_id': approval.tenant_id, 'mapping': mapping,
        'approval_code': mapping.approval_code, 'definition_hash': mapping.definition_hash,
        'app_id': connection.app_id, 'reviewer_open_id': mapping.reviewer_open_id, 'finance_snapshot':finance_snapshot,
        'payload': {'approval_code': mapping.approval_code, 'open_id': sender, 'form': form}}
    instance, created = FeishuApprovalInstance.objects.get_or_create(approval=approval, defaults=defaults)
    if not created and (instance.payload != defaults['payload'] or instance.finance_snapshot != finance_snapshot):
        raise ValidationError('该审批已关联不同的飞书提交内容。')
    if created:
        snapshot = {**approval.workflow_snapshot, 'approval_provider': 'feishu',
            'feishu_mapping_id': mapping.pk, 'feishu_definition_hash': mapping.definition_hash,
            'feishu_reviewer_id': approval.designated_reviewer_id}
        approval.workflow_snapshot = snapshot
        approval.save(update_fields=['workflow_snapshot', 'updated_at'])
    return instance


def native_status(approval):
    if not approval or approval.workflow_snapshot.get('approval_provider') != 'feishu':
        return None
    instance = FeishuApprovalInstance.objects.filter(tenant_id=approval.tenant_id, approval=approval).first()
    if not instance:
        return {'provider': 'feishu', 'status': 'error', 'error': 'INSTANCE_LINK_MISSING'}
    return {'provider': 'feishu', 'status': instance.status, 'instance_code': instance.instance_code,
        'provider_status': instance.provider_status, 'error': instance.last_error}


def submit_instance(instance_id, *, client=None):
    client = client or FeishuNativeClient()
    with transaction.atomic():
        row = FeishuApprovalInstance.objects.select_for_update().select_related('approval', 'mapping').get(pk=instance_id)
        if row.instance_code or row.status in ('submitted', 'finished', 'manual_review', 'blocked'):
            return {'status': row.status}
        if row.lease_until and row.lease_until > timezone.now():
            return {'status': 'busy'}
        if row.approval.status != 'pending' or not row.mapping.enabled:
            row.status = 'blocked'; row.last_error = 'SUBMISSION_NO_LONGER_ALLOWED'
            row.save(update_fields=['status', 'last_error', 'updated_at'])
            return {'status': row.status}
        row.status = 'sending'; row.attempts += 1; row.lease_until = timezone.now() + timedelta(minutes=3)
        row.save(update_fields=['status', 'attempts', 'lease_until', 'updated_at'])
        tenant_id, code, expected_hash = row.tenant_id, row.approval_code, row.definition_hash
        payload = {**row.payload, 'uuid': str(row.submission_uuid)}
    try:
        connection = _connection(tenant_id)
        if connection.app_id != row.app_id or not row.mapping.fixed_assignees_verified or not row.mapping.subscription_verified:
            raise ValidationError('审批连接或映射核验已变化。')
        definition = client.get_definition(connection, code)
        if definition_hash(definition) != expected_hash:
            raise ValidationError('审批定义已变化。')
        response = None
        if row.attempts > 1:
            try:
                recovered = client.get_instance(connection, str(row.submission_uuid))
                if recovered.get('uuid') != str(row.submission_uuid) or recovered.get('approval_code') != code or recovered.get('open_id') != payload['open_id']:
                    raise ValueError('Recovered instance mismatch')
                response = recovered
            except FeishuNativeAPIError as exc:
                if exc.provider_code != 1390003:
                    raise
        if response is None:
            if row.attempts > 5:
                FeishuApprovalInstance.objects.filter(pk=instance_id).update(status='blocked', last_error='NATIVE_SUBMISSION_RETRY_LIMIT', lease_until=None)
                return {'status': 'blocked'}
            response = client.create_instance(connection, payload)
        instance_code = response.get('instance_code')
        if not isinstance(instance_code, str) or not instance_code or len(instance_code) > 120:
            raise ValidationError('缺少有效审批实例编号。')
        with transaction.atomic():
            saved = FeishuApprovalInstance.objects.select_for_update().get(pk=instance_id)
            if saved.instance_code and saved.instance_code != instance_code:
                raise ValidationError('同一提交对应多个审批实例。')
            if saved.instance_code == instance_code:
                saved.lease_until = None
                saved.save(update_fields=['lease_until', 'updated_at'])
                return {'status': saved.status}
            saved.instance_code = instance_code; saved.status = 'submitted'; saved.last_error = ''; saved.lease_until = None
            saved.save(update_fields=['instance_code', 'status', 'last_error', 'lease_until', 'updated_at'])
        return {'status': 'submitted'}
    except Exception:
        # Stable UUID is retained for timeout/crash retries. Never expose response or account data.
        FeishuApprovalInstance.objects.filter(pk=instance_id, instance_code__isnull=True).update(status='retry', last_error='NATIVE_SUBMISSION_UNVERIFIED', lease_until=None, updated_at=timezone.now())
        return {'status': 'retry'}


def dispatch_native_approvals(*, limit=5):
    due = FeishuApprovalInstance.objects.filter(status__in=['queued', 'retry', 'sending'], instance_code__isnull=True).filter(
        Q(lease_until__isnull=True) |
        Q(lease_until__lte=timezone.now())).order_by('updated_at', 'pk')
    results = [submit_instance(pk) for pk in list(due.values_list('pk', flat=True)[:limit])]
    return {'events': dispatch_native_events(limit=limit), 'submissions': results, 'reconciliations': reconcile_due_instances(limit=limit)}


def ensure_native_postable(approval, *, client=None):
    status = native_status(approval)
    if not status:
        return None
    if status['status'] != 'finished' or status.get('provider_status') != 'APPROVED' or not status.get('instance_code'):
        raise ValidationError('飞书审批终态未核验或需要人工复核，暂不能入账。')
    instance = FeishuApprovalInstance.objects.get(tenant_id=approval.tenant_id, approval=approval)
    if FeishuApprovalEvent.objects.filter(tenant_id=approval.tenant_id, event__instance_code=instance.instance_code,
            status__in=['queued', 'processing', 'retry']).exists():
        raise ValidationError('飞书审批事件尚在同步，请稍后刷新重试。')
    try:
        connection = _connection(approval.tenant_id)
        if connection.app_id != instance.app_id:
            raise ValueError('Connection changed')
        authoritative = (client or FeishuNativeClient()).get_instance(connection, instance.instance_code)
        if (authoritative.get('status') != 'APPROVED' or authoritative.get('reverted') is True or
                authoritative.get('instance_code') != instance.instance_code or
                authoritative.get('approval_code') != instance.approval_code or
                authoritative.get('uuid') != str(instance.submission_uuid) or
                authoritative.get('open_id') != instance.payload.get('open_id')):
            raise ValueError('Native approval is not valid for posting')
        return authoritative
    except Exception:
        raise ValidationError('无法确认飞书审批当前仍有效，暂不能入账，请刷新审批状态。')


def payment_form_options(actor, row, business_type):
    mappings = FeishuApprovalMapping.objects.filter(tenant_id=actor.tenant_id, business_type=business_type, enabled=True)
    if not mappings.exists() or row.status != 'draft':
        return None
    from apps.workflows.services import resolve_payment_flow
    if business_type == 'supply_payment_batch':
        lines = list(row.lines.all())
        total = sum((line.amount for line in lines), Decimal(0))
        sources = [('payment_batch', None, total, row.account_snapshot.get('nature'), False)] + [
            (line.kind, line.source_id, line.amount, line.item_snapshot.get('nature') or line.account_snapshot.get('nature'), True) for line in lines]
    else:
        sources = [(row.kind, row.source_id, row.amount, row.item_snapshot.get('nature') or row.account_snapshot.get('nature'), True)]
    try:
        flow, _ = resolve_payment_flow(actor=actor, sources=sources)
        mapping = mappings.filter(flow_key=flow.flow_key).first()
        if not mapping:
            raise ValueError('Native flow mapping missing')
        widgets = mapping.definition.get('form', [])
        if isinstance(widgets, str):
            widgets = json.loads(widgets)
        def options(name):
            matching = [w for w in widgets if w.get('name') == name and w.get('required')]
            if len(matching) != 1 or not isinstance(matching[0].get('option'), list):
                raise ValueError('Invalid form configuration')
            return [{'value': item['value'], 'text': item['text']} for item in matching[0]['option']]
        return {'required': True, 'payment_types': options('付款类型'), 'payment_methods': options('付款方式')}
    except Exception:
        return {'required': True, 'error': '付款流程或飞书模板映射需重新核验。', 'payment_types': [], 'payment_methods': []}


def reconcile_due_instances(*, limit=5, client=None):
    """Recover missed callbacks and monitor approved/unpaid instances for revocation."""
    from .feishu_approval_callback import reconcile_native_event
    client = client or FeishuNativeClient()
    eligible = FeishuApprovalInstance.objects.filter(Q(status='submitted') | Q(status='finished', provider_status='APPROVED'), instance_code__isnull=False,
        updated_at__lte=timezone.now()-timedelta(seconds=60)).filter(
        Q(approval__business_type='supply_payment_request', approval__supply_payment_request__payment__isnull=True) |
        Q(approval__business_type='supply_payment_batch', approval__supply_payment_batch__status='submitted')).order_by('updated_at', 'pk')
    results = []
    for row in list(eligible[:limit]):
        try:
            connection = _connection(row.tenant_id)
            if connection.app_id != row.app_id:
                raise ValueError('Connection changed')
            data = client.get_instance(connection, row.instance_code)
            event = {'app_id': row.app_id, 'instance_code': row.instance_code, 'approval_code': row.approval_code}
            digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:40]
            class CachedClient:
                def get_instance(self, *_args):
                    return data
            outcome = reconcile_native_event(row.tenant_id, f'native-poll:{row.pk}:{digest}', event, client=CachedClient())
            FeishuApprovalInstance.objects.filter(pk=row.pk).update(updated_at=timezone.now())
            results.append({'id': row.pk, 'status': outcome})
        except Exception:
            FeishuApprovalInstance.objects.filter(pk=row.pk).update(last_error='NATIVE_RECONCILIATION_UNVERIFIED', updated_at=timezone.now())
            results.append({'id': row.pk, 'status': 'retry'})
    return results


def enqueue_native_event(tenant_id, event_id, event):
    """Store authenticated identifiers only; acknowledge within the webhook deadline."""
    clean = {key: event.get(key) for key in ('app_id', 'approval_code', 'instance_code')}
    if any(not isinstance(value, str) or not value or len(value) > 120 for value in clean.values()):
        raise ValueError('Invalid event identifiers')
    with transaction.atomic():
        row, created = FeishuApprovalEvent.objects.get_or_create(tenant_id=tenant_id, event_id=event_id, defaults={'event': clean})
        if not created and row.event != clean:
            raise ValueError('Conflicting event identity')
    return 'queued' if created else 'duplicate'


def process_native_event(event_pk, *, client=None):
    from .feishu_approval_callback import reconcile_native_event
    with transaction.atomic():
        row = FeishuApprovalEvent.objects.select_for_update().get(pk=event_pk)
        if row.status in ('done', 'ignored'):
            return {'status': row.status}
        if row.lease_until and row.lease_until > timezone.now():
            return {'status': 'busy'}
        row.attempts += 1; row.status = 'processing'; row.lease_until = timezone.now()+timedelta(minutes=3)
        row.save(update_fields=['attempts', 'status', 'lease_until', 'updated_at'])
        tenant_id, event_id, event = row.tenant_id, row.event_id, row.event
    try:
        outcome = reconcile_native_event(tenant_id, event_id, event, client=client)
        status = 'ignored' if outcome == 'ignored' else 'done'
        FeishuApprovalEvent.objects.filter(pk=event_pk).update(status=status, lease_until=None, last_error='', updated_at=timezone.now())
        return {'status': status}
    except Exception:
        FeishuApprovalEvent.objects.filter(pk=event_pk).update(status='retry', lease_until=None, last_error='NATIVE_EVENT_UNVERIFIED', updated_at=timezone.now())
        return {'status': 'retry'}


def dispatch_native_events(*, limit=5):
    rows = FeishuApprovalEvent.objects.filter(status__in=['queued', 'retry', 'processing']).filter(
        Q(lease_until__isnull=True) | Q(lease_until__lte=timezone.now())).order_by('updated_at', 'pk')
    return [process_native_event(pk) for pk in list(rows.values_list('pk', flat=True)[:limit])]
