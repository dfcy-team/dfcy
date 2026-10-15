"""Procurement configuration; sending is a separately granted capability."""
import json
from urllib.parse import urlsplit
from datetime import date

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied
from apps.integrations.custody import get_custody_backend, CustodyError
from apps.masterdata.models import SupplierMaster
from apps.purchasing.supply_permissions import require_internal_supply_permission, authorize_internal_supplier
from . import services
from .models import NotificationChannel, SupplierGroupBinding, domain_write
from .permissions import VIEW, MANAGE

NOTIFY = 'supply.v2.notify'


def require_notify(actor, supplier_id=None):
    services._internal(actor)
    require_internal_supply_permission(actor, NOTIFY)
    if supplier_id is not None:
        authorize_internal_supplier(actor, NOTIFY, supplier_id)
        authorize_internal_supplier(actor, MANAGE, supplier_id)


def public_base():
    value = getattr(settings, 'SUPPLY_NOTIFICATION_PUBLIC_BASE_URL', 'https://xtsy.dingfengchuangyu.com').rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValidationError('请由部署配置设置正确的 HTTPS 系统入口域名。')
    return value


def channel_for(actor, pk, permission=VIEW):
    if not actor.is_active:
        raise PermissionDenied('采购账号已停用。')
    require_internal_supply_permission(actor, permission)
    obj = NotificationChannel.objects.filter(tenant=actor.tenant, pk=pk).first()
    if not obj:
        raise NotFound('通知通道不存在。')
    return obj


def supplier_for(actor, pk, permission=VIEW):
    if not actor.is_active:
        raise PermissionDenied('采购账号已停用。')
    require_internal_supply_permission(actor, permission)
    authorize_internal_supplier(actor, permission, pk)
    obj = SupplierMaster.objects.filter(tenant=actor.tenant, pk=pk).first()
    if not obj:
        raise NotFound('供应商不存在。')
    return obj


def channel_digest(obj):
    return services.request_hash({'id': obj.pk, 'tenant': obj.tenant_id, 'sender': obj.sender_name,
        'device': obj.device_name, 'credential_digest': obj.credential_digest, 'public_base': public_base()})


def qualified(obj):
    return bool(obj.credential_id and obj.qualified_digest and obj.qualified_digest == channel_digest(obj))


def channel_data(obj):
    return {'id': obj.pk, 'version': obj.version, 'name': obj.name, 'provider': obj.provider,
        'sender_name': obj.sender_name, 'device_name': obj.device_name,
        'credential_configured': bool(obj.credential_id), 'enabled': obj.enabled,
        'qualified': qualified(obj), 'qualification': obj.qualification, 'connectivity': obj.connectivity,
        'last_checked_at': obj.last_checked_at, 'public_base_url': public_base(),
        'live_delivery_enabled': bool(getattr(settings, 'SUPPLY_NOTIFICATION_DELIVERY_ENABLED', False))}


@transaction.atomic
def save_channel(actor, pk, payload, key):
    require_notify(actor)
    services._tenant_lock(actor)
    with domain_write():
        if pk:
            obj = channel_for(actor, pk, NOTIFY)
            if services._prior_event(actor, obj, 'channel_saved', key, payload):
                return obj
            services._version(obj, payload['expected_version'])
            for name in ('name', 'sender_name', 'device_name'):
                setattr(obj, name, payload[name])
            enabled = payload.get('enabled', False)
            if enabled and not qualified(obj):
                raise ValidationError('请先完成两天的真实外部群、文件与填写验收，再启用自动投递。')
            if not qualified(obj):
                obj.connectivity, obj.last_checked_at = 'unknown', None
            obj.enabled, obj.enabled_by = enabled, actor if enabled else None
            obj.version += 1
            obj.save()
        else:
            # Creation is keyed by an event, not by mutable channel display names.
            previous = services.BusinessEvent.objects.filter(tenant=actor.tenant,
                aggregate_type='notificationchannel', action='channel_created', request_key=services._key(key)).first()
            if previous:
                services._matching_replay(previous, services.request_hash(payload))
                return channel_for(actor, previous.aggregate_id, NOTIFY)
            obj = NotificationChannel.objects.create(tenant=actor.tenant, created_by=actor,
                **{name: payload[name] for name in ('name', 'sender_name', 'device_name')})
        services._event(actor, obj, 'channel_saved' if pk else 'channel_created', key, payload)
    return obj


@transaction.atomic
def credentials(actor, pk, payload, key):
    require_notify(actor)
    services._tenant_lock(actor)
    obj = channel_for(actor, pk, NOTIFY)
    # Only a high-entropy digest enters audit/BusinessEvent, never the credential.
    safe_payload = {'expected_version': payload['expected_version'], 'reason': payload['reason'],
                    'credential_digest': services.request_hash({'robot_id': payload['robot_id']})}
    if services._prior_event(actor, obj, 'channel_credentials', key, safe_payload):
        return obj
    services._version(obj, payload['expected_version'])
    values = {'credential_type': 'supply_worktool', 'reference_version': obj.credential_version + 1,
        'metadata': {'tenant_id': obj.tenant_id, 'supply_channel_id': obj.pk},
        'idempotency_key': f'supply-channel-{obj.tenant_id}-{obj.pk}-{services.request_hash(key)}',
        'operation_id': f'supply-channel-{obj.pk}-v{obj.credential_version+1}',
        'secret': json.dumps({'robot_id': payload['robot_id']}, separators=(',', ':'))}
    try:
        custody = get_custody_backend()
        if obj.credential_id:
            stored = custody.rotate_secrets(previous_credential_id=obj.credential_id,
                previous_token_id=obj.token_id, **values)
        else:
            stored = custody.store_secrets(**values)
    except CustodyError:
        raise ValidationError('凭据托管未配置或保存失败，请先配置系统的独立凭据托管服务。') from None
    finally:
        values.clear()
    with domain_write():
        obj.credential_id, obj.token_id = stored['credential_id'], stored['token_id']
        obj.credential_version = int(stored.get('reference_version') or obj.credential_version + 1)
        obj.credential_digest = safe_payload['credential_digest']
        obj.enabled, obj.enabled_by, obj.qualified_digest = False, None, ''
        obj.connectivity, obj.last_checked_at = 'unknown', None
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'channel_credentials', key, safe_payload)
    return obj


def resolve_robot(obj):
    if not obj.credential_id:
        raise ValidationError('通道尚未维护机器人凭据。')
    try:
        raw = get_custody_backend().retrieve_secret(obj.credential_id)
        value = json.loads(raw)
        robot = value.get('robot_id')
        if not isinstance(robot, str) or not robot or len(robot) > 200:
            raise ValueError()
        return robot
    except (CustodyError, ValueError, TypeError):
        raise ValidationError('机器人凭据不可用，请核对托管服务或重新维护凭据。') from None


@transaction.atomic
def qualify_channel(actor, pk, payload, key):
    require_notify(actor)
    services._tenant_lock(actor)
    obj = channel_for(actor, pk, NOTIFY)
    if services._prior_event(actor, obj, 'channel_qualified', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    first, second = services._date(payload['first_day']), services._date(payload['second_day'])
    if (not obj.credential_id or not first < second <= services.business_date()
        or any(payload[name] is not True for name in ('contains_external_member', 'documents_opened', 'supplier_saved', 'automatic_without_confirmation'))
        or min(payload['first_day_count'], payload['second_day_count']) < 6 or not payload['evidence'].strip()):
        raise ValidationError('需记录两个不同日期各至少6条、真实外部成员、文件打开和供应商保存且无逐条确认的验收证据。')
    with domain_write():
        obj.qualification = json.loads(json.dumps({k: v for k,v in payload.items() if k != 'expected_version'}, default=str))
        obj.qualified_digest = channel_digest(obj)
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'channel_qualified', key, payload)
    return obj


def binding_digest(obj):
    return services.request_hash({'supplier': obj.supplier_id, 'channel': channel_digest(obj.channel),
        'target_title': obj.target_title, 'group_name': obj.group_name,
        'external': obj.contains_external_member, 'sender_member': obj.sender_member_confirmed,
        'unique': obj.unique_target_confirmed})


def binding_verified(obj):
    return bool(obj.verified_digest and obj.verified_digest == binding_digest(obj))


def binding_data(obj):
    if not obj:
        return None
    fields = ('id', 'version', 'supplier_id', 'channel_id', 'group_name', 'target_title', 'member_count',
        'group_note', 'contains_external_member', 'sender_member_confirmed', 'unique_target_confirmed', 'evidence', 'enabled')
    return {**{name: getattr(obj, name) for name in fields}, 'channel_name': obj.channel.name,
        'sender_name': obj.channel.sender_name, 'verified': binding_verified(obj), 'verification_method': 'manual'}


@transaction.atomic
def save_binding(actor, supplier_id, payload, key):
    require_notify(actor, supplier_id)
    services._tenant_lock(actor)
    supplier = supplier_for(actor, supplier_id, MANAGE)
    obj = SupplierGroupBinding.objects.filter(tenant=actor.tenant, supplier=supplier).first()
    if obj and services._prior_event(actor, obj, 'group_binding_saved', key, payload):
        return obj
    if payload['expected_version'] != (obj.version if obj else 0):
        raise ValidationError('群绑定已变化，请重新加载。')
    channel = channel_for(actor, payload['channel_id'])
    title = payload['target_title'].strip()
    if not title or len(title) > 60 or title[0].isdigit() or any(ch in title for ch in '- @()\r\n') or title.endswith(('...', '…')):
        raise ValidationError('请使用可唯一定位且完整显示的群名或群备注，勿含空格、减号、括号或@，也不要以数字开头。')
    is_verified = all(payload[name] for name in ('contains_external_member', 'sender_member_confirmed', 'unique_target_confirmed')) and bool(payload['evidence'].strip())
    if payload.get('enabled') and not is_verified:
        raise ValidationError('请先核实外部成员、发送账号群成员身份及目标唯一性，并填写核验依据。')
    with domain_write():
        if obj is None:
            obj = SupplierGroupBinding(tenant=actor.tenant, created_by=actor, supplier=supplier)
        else:
            obj.version += 1
        obj.channel = channel
        for name in ('group_name', 'member_count', 'group_note', 'contains_external_member',
                     'sender_member_confirmed', 'unique_target_confirmed', 'evidence', 'enabled'):
            setattr(obj, name, payload[name])
        obj.target_title = title
        obj.verified_digest = binding_digest(obj) if is_verified else ''
        obj.save()
        services._event(actor, obj, 'group_binding_saved', key, payload)
    return obj


def snapshot_binding(obj):
    return {'binding_id': obj.pk, 'binding_digest': binding_digest(obj), 'channel_id': obj.channel_id,
        'channel_digest': channel_digest(obj.channel), 'channel_name': obj.channel.name,
        'sender_name': obj.channel.sender_name, 'device_name': obj.channel.device_name,
        'group_name': obj.group_name, 'target_title': obj.target_title,
        'official_chat_id': obj.official_chat_id, 'supplier_id': obj.supplier_id}


def callback_link(obj):
    token = signing.Signer(salt='supply-worktool-callback').sign(f'{obj.pk}:{channel_digest(obj)}')
    from urllib.parse import urlencode
    return public_base() + f'/api/supply-notifications/worktool/{obj.pk}/callback/?' + urlencode({'signature': token})


def check_callback(obj, token):
    try:
        decoded = signing.Signer(salt='supply-worktool-callback').unsign(token)
        if decoded != f'{obj.pk}:{channel_digest(obj)}':
            raise ValueError()
    except (signing.BadSignature, ValueError, TypeError):
        raise PermissionDenied('执行回调凭据无效。') from None
