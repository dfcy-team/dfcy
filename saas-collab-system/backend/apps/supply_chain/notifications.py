"""Atomic preparation, independently tracked parts, and conservative retries."""
import hashlib
import json
import secrets
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Exists, OuterRef
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from . import services, notification_config as cfg
from .documents import purchase_workbook, sku_labels
from .models import (NotificationOutbox, NotificationPart, NotificationAttempt, NotificationEvidence,
    NotificationReceipt, NotificationDownload, SupplierGroupBinding, NotificationChannel, PurchaseOrder, domain_write)
from .permissions import internal_orders, VIEW, MANAGE
from .worktool import WorkTool, TransportError, RateLimited

MESSAGES = {'channel_not_verified': '尚未绑定或验证通知通道。', 'missing_binding': '请为此订单明确绑定供应商目标群。',
    'binding_changed': '群绑定或发送账号已变化，请核对原目标，未发送时可刷新绑定。',
    'binding_not_verified': '请核实并启用供应商群绑定。', 'channel_disabled': '发送通道未启用。',
    'channel_not_qualified': '真实外部群验收尚未登记或配置已变化。',
    'live_delivery_disabled': '系统对外投递开关尚未开启。', 'permission_revoked': '通道启用人的授权已失效。',
    'source_unavailable': '原采购订单或操作账号已停用。', 'sender_offline': '发送端离线，恢复在线后可继续。',
    'connectivity_unknown': '尚不能确认发送端在线，请检查凭据或通道。',
    'rate_limited': '通道请求频率受控，等待下一次处理。', 'prepare_failed': '附件准备失败，请检查后重新准备。'}


def rows_for(actor, permission=VIEW):
    return NotificationOutbox.objects.filter(tenant=actor.tenant,
        order__in=internal_orders(actor, PurchaseOrder.objects.all(), permission)).select_related('order__supplier', 'binding__channel')


def outbox_for(actor, pk, permission=VIEW):
    obj = rows_for(actor, permission).filter(pk=pk).first()
    if not obj:
        raise NotFound('通知记录不可访问。')
    return obj


def part_for(obj, pk):
    part = obj.parts.filter(pk=pk).first()
    if not part:
        raise NotFound('通知部件不存在。')
    return part


def unresolved_attempts(*, include_sending=False):
    states = ('sending', 'accepted', 'unknown') if include_sending else ('accepted', 'unknown')
    observed = NotificationEvidence.objects.filter(attempt_id=OuterRef('pk'))
    newer = NotificationAttempt.objects.filter(part_id=OuterRef('part_id'), number__gt=OuterRef('number'))
    return NotificationAttempt.objects.filter(outcome__in=states, part__status__in=states).annotate(
        observed=Exists(observed), superseded=Exists(newer)).filter(observed=False, superseded=False)


def capture_binding(obj):
    """Only called at confirmation, or by an explicit authorized retarget action."""
    binding = SupplierGroupBinding.objects.filter(tenant=obj.tenant, supplier_id=obj.order.supplier_id).select_related('channel').first()
    if binding:
        obj.binding, obj.target_snapshot = binding, cfg.snapshot_binding(binding)


def blocked(obj, reason, *, status='blocked'):
    with domain_write():
        changed = obj.status != status or obj.blocked_reason != reason
        obj.status, obj.blocked_reason = status, reason
        obj.next_attempt_at = timezone.now() + timedelta(seconds=30)
        if changed:
            obj.version += 1
        obj.save()


def guard(obj, *, live=True):
    if obj.order.status != 'confirmed' or not obj.created_by.is_active:
        return 'source_unavailable'
    if not obj.binding_id or not obj.target_snapshot:
        return 'missing_binding'
    binding = SupplierGroupBinding.objects.filter(pk=obj.binding_id, tenant=obj.tenant).select_related('channel').first()
    if not binding or cfg.snapshot_binding(binding) != obj.target_snapshot:
        return 'binding_changed'
    if not binding.enabled or not cfg.binding_verified(binding):
        return 'binding_not_verified'
    channel = binding.channel
    if not channel.enabled:
        return 'channel_disabled'
    if not cfg.qualified(channel):
        return 'channel_not_qualified'
    try:
        if not internal_orders(obj.created_by, PurchaseOrder.objects.all(), MANAGE).filter(pk=obj.order_id).exists():
            return 'permission_revoked'
        if not channel.enabled_by or not channel.enabled_by.is_active:
            return 'permission_revoked'
        cfg.require_notify(channel.enabled_by, obj.order.supplier_id)
        if not internal_orders(channel.enabled_by, PurchaseOrder.objects.all(), MANAGE).filter(pk=obj.order_id).exists():
            return 'permission_revoked'
    except PermissionDenied:
        return 'permission_revoked'
    if live and not getattr(settings, 'SUPPLY_NOTIFICATION_DELIVERY_ENABLED', False):
        return 'live_delivery_disabled'
    return ''


def prepare(actor, pk, payload, key):
    services._internal(actor)
    obj = outbox_for(actor, pk, MANAGE)
    if services._prior_event(actor, obj, 'notification_prepared', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if obj.prepared_at:
        return obj
    snapshot = obj.event.payload.get('purchase_snapshot')
    if not snapshot or snapshot.get('version') != obj.order_version or not snapshot.get('prices_complete'):
        raise ValidationError('确认事件的有效采购快照不完整，不能发送通知。')
    from .supplier_products import enrich_snapshot
    from .supplier_product_images import load_product_images
    snapshot = enrich_snapshot(snapshot, actor.tenant_id)
    images = load_product_images(snapshot, actor.tenant_id)
    supplier_url = cfg.public_base() + f'/supplier/orders/{obj.order_id}'
    lines = [f'【采购订单】{snapshot["number"]}', f'供应商：{snapshot["supplier_name"]}', f'国家：{snapshot["country_name"]}',
             f'总数量：{snapshot["total_quantity"]}', f'总金额：{snapshot["total_amount"]}']
    if snapshot.get('reference_number'):
        lines.append(f'备注单号：{snapshot["reference_number"]}')
    summary = '\n'.join(lines)
    materials = [('summary', summary, b'', '', ''),
        ('excel', '', purchase_workbook(snapshot, images=images), f'PO-{obj.order_id}-v{obj.order_version}-shipment.xlsx',
         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ('pdf', '', sku_labels(snapshot), f'PO-{obj.order_id}-v{obj.order_version}-labels.pdf', 'application/pdf'),
        ('link', f'查看采购单、下载附件、填写发货批次和上传箱号文件：\n{supplier_url}', b'', '', '')]
    if any(len(body) > 10 * 1024 * 1024 for _,_,body,_,_ in materials):
        raise ValidationError('采购通知附件超过10MB，请拆分订单后重试。')
    # Read remote product pictures before taking a database lock. Revalidate
    # idempotency/version after preparation so concurrent workers commit once.
    with transaction.atomic():
        services._tenant_lock(actor)
        obj = outbox_for(actor, pk, MANAGE)
        if services._prior_event(actor, obj, 'notification_prepared', key, payload):
            return obj
        services._version(obj, payload['expected_version'])
        if obj.prepared_at:
            return obj
        with domain_write():
            for index, (kind, text, body, name, mime) in enumerate(materials, 1):
                digest = hashlib.sha256(body or text.encode()).hexdigest()
                NotificationPart.objects.create(tenant=actor.tenant, created_by=actor, outbox=obj, kind=kind,
                    sequence=index, text=text, body=body, object_name=name, content_type=mime, sha256=digest, size=len(body))
            obj.prepared_at, obj.summary, obj.supplier_url = timezone.now(), summary, supplier_url
            obj.total_quantity, obj.total_amount = snapshot['total_quantity'], snapshot['total_amount']
            obj.blocked_reason = guard(obj)
            obj.status = 'blocked' if obj.blocked_reason else 'queued'
            obj.version += 1
            obj.save()
            services._event(actor, obj, 'notification_prepared', key, payload, audit={'snapshot_version': obj.order_version,
                'parts': list(obj.parts.values('kind', 'sha256', 'size', 'object_name'))})
    return obj


@transaction.atomic
def retarget(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = outbox_for(actor, pk, MANAGE)
    cfg.require_notify(actor, obj.order.supplier_id)
    if services._prior_event(actor, obj, 'notification_retargeted', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if NotificationAttempt.objects.filter(part__outbox=obj).exists():
        raise ValidationError('已经产生发送尝试，不能改投另一目标群；请先核对原消息。')
    with domain_write():
        capture_binding(obj)
        if not obj.binding_id:
            raise ValidationError('供应商尚未登记目标群。')
        obj.blocked_reason = guard(obj)
        obj.status = 'blocked' if obj.blocked_reason else 'queued'
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'notification_retargeted', key, payload, audit={'target_snapshot': obj.target_snapshot})
    return obj


def aggregate(obj):
    states = set(obj.parts.values_list('status', flat=True))
    if not states:
        return
    state = ('delivered' if states == {'delivered'} else 'unknown' if 'unknown' in states else
             'sending' if 'sending' in states else 'failed' if 'failed' in states else
             'queued' if 'pending' in states else 'awaiting_execution' if 'accepted' in states else 'awaiting_verification')
    with domain_write():
        obj.status, obj.blocked_reason = state, ''
        obj.next_attempt_at = None
        obj.version += 1
        obj.save()


def data(obj, *, detail=True):
    result = {'id': obj.pk, 'version': obj.version, 'order_id': obj.order_id, 'order_number': obj.order.number,
        'order_version': obj.order_version, 'supplier_name': obj.order.supplier.name,
        'status': obj.status, 'blocked_reason': obj.blocked_reason,
        'blocked_message': MESSAGES.get(obj.blocked_reason, obj.blocked_reason), 'prepared': bool(obj.prepared_at),
        'total_quantity': obj.total_quantity, 'total_amount': str(obj.total_amount) if obj.total_amount is not None else None,
        'summary': obj.summary, 'supplier_url': obj.supplier_url, 'target_snapshot': obj.target_snapshot}
    if not obj.prepared_at:
        snapshot = obj.event.payload.get('purchase_snapshot') or {}
        result.update(total_quantity=snapshot.get('total_quantity'), total_amount=snapshot.get('total_amount'))
    if detail:
        result['parts'] = [{'id': p.pk, 'version': p.version, 'kind': p.kind, 'status': p.status, 'text': p.text,
            'object_name': p.object_name, 'sha256': p.sha256, 'size': p.size, 'can_retry': p.status == 'failed',
            'attempts': list(p.attempts.order_by('-number').values('id', 'number', 'outcome', 'provider_message_id', 'error_code', 'started_at', 'finished_at')),
            'evidence': list(p.evidence.order_by('-id').values('result', 'evidence', 'created_at'))}
            for p in obj.parts.all()]
    return result


@transaction.atomic
def retry(actor, pk, part_id, payload, key):
    services._tenant_lock(actor)
    obj = outbox_for(actor, pk, MANAGE)
    cfg.require_notify(actor, obj.order.supplier_id)
    part = part_for(obj, part_id)
    if services._prior_event(actor, part, 'notification_retry', key, payload):
        return obj
    services._version(part, payload['expected_version'])
    if part.status != 'failed':
        raise ValidationError('仅确定未完成的失败部件可重试；结果未知时先核对群内消息并停止原指令。')
    reason = guard(obj, live=False)
    if reason:
        raise ValidationError(MESSAGES.get(reason, reason))
    with domain_write():
        part.status, part.next_attempt_at = 'pending', timezone.now()
        part.version += 1
        part.save()
        aggregate(obj)
        services._event(actor, part, 'notification_retry', key, payload)
    return obj


@transaction.atomic
def verify(actor, pk, part_id, payload, key):
    services._tenant_lock(actor)
    obj = outbox_for(actor, pk, MANAGE)
    cfg.require_notify(actor, obj.order.supplier_id)
    part = part_for(obj, part_id)
    if services._prior_event(actor, part, 'notification_verified', key, payload):
        return obj
    services._version(part, payload['expected_version'])
    attempt = part.attempts.order_by('-number').first()
    if not attempt or part.status in ('pending', 'sending', 'delivered'):
        raise ValidationError('请核对已有发送尝试，不能提前确认或改写已核实送达的部件。')
    if not payload['evidence'].strip():
        raise ValidationError('请填写实际目标群、消息编号及观察结果等证据。')
    if payload['result'] == 'not_delivered' and part.status in ('accepted', 'executed', 'unknown') and not payload['execution_stopped']:
        raise ValidationError('请先确认工具已停止原指令且没有待执行任务，避免重复发送。')
    with domain_write():
        NotificationEvidence.objects.create(tenant=actor.tenant, created_by=actor, part=part, attempt=attempt,
            result=payload['result'], evidence=payload['evidence'], execution_stopped=payload['execution_stopped'])
        part.status = 'delivered' if payload['result'] == 'delivered' else 'failed'
        part.version += 1
        part.save()
        aggregate(obj)
        services._event(actor, part, 'notification_verified', key, payload)
    return obj


def check_channel(actor, pk, payload, key, *, adapter=None):
    cfg.require_notify(actor)
    with transaction.atomic():
        services._tenant_lock(actor)
        channel = cfg.channel_for(actor, pk, cfg.NOTIFY)
        if services._prior_event(actor, channel, 'channel_checked', key, payload):
            return channel
        services._version(channel, payload['expected_version'])
        digest = cfg.channel_digest(channel)
    try:
        state = 'online' if (adapter or WorkTool()).online(channel) else 'offline'
    except RateLimited:
        raise ValidationError('通道请求频率受控，请稍后再检查。') from None
    except (TransportError, ValidationError):
        state = 'unknown'
    with transaction.atomic(), domain_write():
        services._tenant_lock(actor)
        channel = cfg.channel_for(actor, pk, cfg.NOTIFY)
        if cfg.channel_digest(channel) != digest:
            raise ValidationError('检查期间通道配置发生变化，请重新检查。')
        channel.connectivity, channel.last_checked_at = state, timezone.now()
        channel.version += 1
        channel.save()
        services._event(actor, channel, 'channel_checked', key, payload, audit={'connectivity': state})
    return channel


@transaction.atomic
def record_result(channel, payload, *, source='callback'):
    message_id = str(payload.get('messageId') or '')
    attempt = NotificationAttempt.objects.filter(channel=channel, provider_message_id=message_id).select_related('part__outbox').first()
    if not attempt:
        raise NotFound('未找到对应的已受理指令。')
    services._tenant_lock(attempt.created_by)
    part = NotificationPart.objects.get(pk=attempt.part_id)
    obj = NotificationOutbox.objects.select_related('order').get(pk=part.outbox_id)
    expected_type = 218 if part.kind in ('excel', 'pdf') else 203
    clean = {name: payload.get(name) for name in ('messageId', 'errorCode', 'type', 'successList', 'failList')}
    digest = services.request_hash(clean)
    if NotificationReceipt.objects.filter(attempt=attempt, digest=digest).exists():
        return obj
    successes, failures, error = clean['successList'], clean['failList'], clean['errorCode']
    target = attempt.target_snapshot['target_title']
    if clean['type'] != expected_type or not isinstance(successes, list) or not isinstance(failures, list) or isinstance(error, bool) or not isinstance(error, int):
        outcome, error_code = 'unknown', 'execution_schema_unknown'
    elif error == 0 and successes == [target] and not failures:
        outcome, error_code = 'executed', ''
    elif target in failures and target not in successes and error != 0:
        outcome, error_code = 'failed', f'execution_{error}'
    else:
        outcome, error_code = 'unknown', 'execution_target_unknown'
    received_success = outcome == 'executed'
    prior_results = attempt.receipts.values_list('result', flat=True)
    for prior in prior_results:
        same_type = prior.get('type') == expected_type
        prior_success = same_type and type(prior.get('errorCode')) is int and prior['errorCode'] == 0 and prior.get('successList') == [target] and prior.get('failList') == []
        prior_failure = (same_type and isinstance(prior.get('errorCode'), int) and not isinstance(prior.get('errorCode'), bool)
            and prior['errorCode'] != 0 and isinstance(prior.get('failList'), list)
            and target in prior['failList'] and isinstance(prior.get('successList'), list) and target not in prior['successList'])
        if (prior_success and outcome == 'failed') or (prior_failure and outcome == 'executed'):
            outcome, error_code = 'unknown', 'execution_conflict'
            break
    with domain_write():
        NotificationReceipt.objects.create(tenant=channel.tenant, created_by=attempt.created_by,
            attempt=attempt, digest=digest, source=source, result=clean)
        attempt.outcome, attempt.error_code, attempt.finished_at = outcome, error_code, timezone.now()
        attempt.version += 1
        attempt.save()
        latest = part.attempts.order_by('-number').first()
        # A verified observation has higher evidential weight than a tool callback.
        has_observation = part.evidence.filter(attempt=attempt).exists()
        if part.status != 'delivered':
            if latest.pk == attempt.pk and not has_observation:
                part.status = outcome
            elif received_success:
                # A late success contradicts the earlier non-delivery assessment.
                part.status = 'unknown'
            part.version += 1
            part.save()
        aggregate(obj)
    return obj


def reconcile(actor, pk, payload, key, *, adapter=None):
    with transaction.atomic():
        services._tenant_lock(actor)
        obj = outbox_for(actor, pk, MANAGE)
        cfg.require_notify(actor, obj.order.supplier_id)
        if services._prior_event(actor, obj, 'notification_reconciled', key, payload):
            return obj
        services._version(obj, payload['expected_version'])
        attempt = unresolved_attempts().filter(part__outbox=obj,
            provider_message_id__isnull=False).select_related('channel').order_by('started_at').first()
    if not attempt:
        return obj
    try:
        result = (adapter or WorkTool()).result(attempt.channel, attempt.provider_message_id)
    except (TransportError, ValidationError):
        raise ValidationError('暂未取得明确执行结果，原消息不会自动重发，请稍后核对。') from None
    if result:
        record_result(attempt.channel, result, source='query')
    with transaction.atomic(), domain_write():
        services._tenant_lock(actor)
        obj = outbox_for(actor, pk, MANAGE)
        cfg.require_notify(actor, obj.order.supplier_id)
        if not services._prior_event(actor, obj, 'notification_reconciled', key, payload):
            services._event(actor, obj, 'notification_reconciled', key, payload,
                            audit={'attempt_id': attempt.pk, 'result_available': bool(result)})
    return obj


@transaction.atomic
def _claim(pk):
    obj = NotificationOutbox.objects.select_related('order__supplier', 'binding__channel', 'created_by').get(pk=pk)
    services._tenant_lock(obj.created_by)
    # Configuration may change while waiting for the tenant lock.
    obj = NotificationOutbox.objects.select_related('order__supplier', 'binding__channel', 'created_by').get(pk=pk)
    reason = guard(obj)
    if reason:
        blocked(obj, reason)
        return None
    if obj.parts.filter(status__in=('unknown', 'sending')).exists():
        return None
    part = obj.parts.filter(status='pending', next_attempt_at__lte=timezone.now()).order_by('sequence').first()
    if not part:
        return None
    channel = obj.binding.channel
    if not channel.last_checked_at or channel.last_checked_at < timezone.now() - timedelta(seconds=60):
        return None
    if channel.connectivity != 'online':
        blocked(obj, 'sender_offline' if channel.connectivity == 'offline' else 'connectivity_unknown', status='offline')
        return None
    with domain_write():
        number = (part.attempts.order_by('-number').values_list('number', flat=True).first() or 0) + 1
        attempt = NotificationAttempt.objects.create(tenant=obj.tenant, created_by=channel.enabled_by,
            channel=channel, part=part, number=number, target_snapshot=obj.target_snapshot)
        part.status, part.version = 'sending', part.version + 1
        part.save()
        aggregate(obj)
    return attempt


@transaction.atomic
def _finish(attempt_id, outcome, *, message_id=None, error_code=''):
    attempt = NotificationAttempt.objects.select_related('part__outbox').get(pk=attempt_id)
    services._tenant_lock(attempt.created_by)
    part = NotificationPart.objects.get(pk=attempt.part_id)
    with domain_write():
        attempt.outcome, attempt.provider_message_id = outcome, message_id
        attempt.error_code = error_code
        attempt.finished_at = timezone.now() if outcome not in ('accepted', 'sending') else None
        attempt.version += 1
        attempt.save()
        part.status = 'pending' if outcome == 'not_submitted' else outcome
        if outcome == 'not_submitted':
            part.next_attempt_at = timezone.now() + timedelta(seconds=2)
        part.version += 1
        part.save()
        aggregate(attempt.part.outbox)


@transaction.atomic
def _file_grant(attempt):
    token = secrets.token_urlsafe(32)
    with domain_write():
        NotificationDownload.objects.create(tenant=attempt.tenant, created_by=attempt.created_by, attempt=attempt,
            token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(minutes=30))
    return cfg.public_base() + f'/api/supply-notifications/files/{attempt.pk}/{token}/'


@transaction.atomic
def download_material(attempt_id, token):
    grant = NotificationDownload.objects.select_for_update().filter(attempt_id=attempt_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest()).select_related('attempt__part').first()
    if not grant or grant.expires_at <= timezone.now() or grant.download_count >= 10:
        raise NotFound('文件下载授权已失效。')
    part = grant.attempt.part
    body = bytes(part.body)
    if part.kind not in ('excel', 'pdf') or hashlib.sha256(body).hexdigest() != part.sha256:
        raise NotFound('文件内容不可用。')
    with domain_write():
        grant.download_count += 1
        grant.version += 1
        grant.save()
    return part, body


@transaction.atomic
def reap_uncertain(pk):
    obj = NotificationOutbox.objects.select_related('created_by').get(pk=pk)
    services._tenant_lock(obj.created_by)
    stale = list(unresolved_attempts(include_sending=True).filter(part__outbox=obj, outcome__in=('sending', 'accepted'),
        started_at__lt=timezone.now() - timedelta(minutes=10)))
    for attempt in stale:
        part = NotificationPart.objects.get(pk=attempt.part_id)
        if part.attempts.order_by('-number').first().pk == attempt.pk and part.status in ('sending', 'accepted'):
            with domain_write():
                attempt.outcome, attempt.error_code = 'unknown', 'execution_deadline_unknown'
                attempt.version += 1
                attempt.save()
                part.status, part.version = 'unknown', part.version + 1
                part.save()
    if stale:
        aggregate(obj)


def dispatch_one(pk, *, adapter=None):
    """No database transaction spans HTTP. A crashed claim becomes unknown."""
    adapter = adapter or WorkTool()
    obj = NotificationOutbox.objects.select_related('order', 'created_by', 'binding__channel').get(pk=pk)
    if not obj.prepared_at:
        try:
            obj = prepare(obj.created_by, obj.pk, {'expected_version': obj.version}, f'auto-prepare-{obj.pk}')
        except (ValidationError, PermissionDenied):
            blocked(obj, 'prepare_failed')
            return 'blocked'
    reason = guard(obj)
    if reason:
        blocked(obj, reason)
        return 'blocked'
    reap_uncertain(pk)
    obj.refresh_from_db()
    channel = SupplierGroupBinding.objects.select_related('channel').get(pk=obj.binding_id).channel
    if not channel.last_checked_at or channel.last_checked_at < timezone.now() - timedelta(seconds=60):
        try:
            check_channel(channel.enabled_by, channel.pk, {'expected_version': channel.version},
                          f'auto-check-{channel.pk}-{channel.version}', adapter=adapter)
        except ValidationError:
            return 'wait'
        return 'checked'
    if not obj.parts.filter(status='pending').exists() or obj.status == 'unknown':
        unresolved = unresolved_attempts().filter(part__outbox=obj,
            provider_message_id__isnull=False, started_at__lt=timezone.now()-timedelta(seconds=45)).order_by('started_at').first()
        if unresolved:
            try:
                result = adapter.result(channel, unresolved.provider_message_id)
                if result:
                    record_result(channel, result, source='query')
                    return 'reconciled'
            except RateLimited:
                return 'rate_limited'
            except (TransportError, ValidationError):
                pass
            with domain_write():
                obj.next_attempt_at = timezone.now() + timedelta(seconds=45)
                obj.version += 1
                obj.save()
            return 'waiting_execution'
    attempt = _claim(pk)
    if not attempt:
        return 'idle'
    try:
        channel = NotificationChannel.objects.get(pk=attempt.channel_id)
        current = NotificationOutbox.objects.select_related('order', 'created_by').get(pk=pk)
        if guard(current) or cfg.channel_digest(channel) != attempt.target_snapshot['channel_digest']:
            _finish(attempt.pk, 'failed', error_code='configuration_changed_before_send')
            return 'blocked'
        part = NotificationPart.objects.get(pk=attempt.part_id)
        file_url = _file_grant(attempt) if part.kind in ('excel', 'pdf') else None
        message_id = adapter.send(channel, attempt.target_snapshot['target_title'], text=part.text,
            file_url=file_url, object_name=part.object_name)
    except RateLimited:
        _finish(attempt.pk, 'not_submitted', error_code='rate_limited')
        return 'rate_limited'
    except TransportError as exc:
        _finish(attempt.pk, 'unknown' if exc.ambiguous else 'failed', error_code=exc.code)
        return 'unknown' if exc.ambiguous else 'failed'
    except ValidationError:
        _finish(attempt.pk, 'failed', error_code='credential_unavailable')
        return 'failed'
    except Exception:
        # Includes a crash after submitting but before recording the response.
        _finish(attempt.pk, 'unknown', error_code='delivery_result_unknown')
        return 'unknown'
    try:
        _finish(attempt.pk, 'accepted', message_id=message_id)
    except IntegrityError:
        _finish(attempt.pk, 'unknown', error_code='duplicate_message_id')
        return 'unknown'
    return 'accepted'


def dispatch_due(*, limit=20, dry_run=False, adapter=None):
    now = timezone.now()
    from django.db.models import Q, F
    pending = NotificationPart.objects.filter(outbox_id=OuterRef('pk'), status='pending')
    watch = unresolved_attempts(include_sending=True).filter(part__outbox_id=OuterRef('pk')).filter(
        Q(outcome='sending') | Q(provider_message_id__isnull=False))
    rows = NotificationOutbox.objects.exclude(status='delivered').annotate(has_pending=Exists(pending), has_watch=Exists(watch)).filter(
        Q(prepared_at__isnull=True) | Q(has_pending=True) & ~Q(status='unknown') | Q(has_watch=True)).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)).order_by(F('next_attempt_at').asc(nulls_first=True), 'id')
    result = {'prepared_or_processed': 0, 'dry_run': dry_run, 'live_delivery_enabled': bool(getattr(settings, 'SUPPLY_NOTIFICATION_DELIVERY_ENABLED', False)), 'outcomes': []}
    for obj in rows.select_related('order', 'created_by', 'binding__channel')[:limit]:
        if dry_run:
            outcome = guard(obj) or ('ready' if obj.prepared_at else 'needs_preparation')
        else:
            try:
                outcome = dispatch_one(obj.pk, adapter=adapter)
            except (ValidationError, PermissionDenied):
                outcome = 'blocked'
        result['outcomes'].append({'notification_id': obj.pk, 'outcome': outcome})
        result['prepared_or_processed'] += 1
        if outcome == 'rate_limited':
            break
    return result
