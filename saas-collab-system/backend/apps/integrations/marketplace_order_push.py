"""Official Lazada/TikTok order notifications, independent of API pull transport."""
import hashlib
import hmac
import json
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .custody import CustodyError, get_custody_backend
from .models import MarketplaceStoreAuthorization, PlatformIntegrationConfig, WebhookEvent, marketplace_authorization_api_type
from .raw_services import archive_webhook_payload


def verify_signature(app_key, body, secret, signature):
    if not app_key or not secret or not isinstance(signature, str) or not signature.isascii():
        return False
    expected = hmac.new(secret.encode(), str(app_key).encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _text(value, limit=191):
    if type(value) is int and value > 0:
        value = str(value)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('Invalid identifier')
    return value


def _time(value, milliseconds=False):
    if type(value) is not int or value <= 0:
        raise ValueError('Invalid timestamp')
    return datetime.fromtimestamp(value / 1000 if milliseconds else value, dt_timezone.utc)


def parse_event(platform, body):
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
        raise ValueError('Invalid event')
    data = payload['data']
    if platform == 'lazada':
        if type(payload.get('message_type')) is not int or payload['message_type'] != 0:
            raise ValueError('Unsupported event')
        shop = _text(payload.get('seller_id'))
        site = _text(payload.get('site'), 20)
        if site not in {'lazada_ph', 'lazada_my', 'lazada_th', 'lazada_vn', 'lazada_id', 'lazada_sg'}:
            raise ValueError('Invalid site')
        order = _text(data.get('trade_order_id'))
        line = _text(data.get('trade_order_line_id'))
        reverse = _text(data['reverse_order_id']) if 'reverse_order_id' in data else ''
        reverse_line = _text(data['reverse_order_line_id']) if reverse else ''
        at = _time(data.get('status_update_time'))
        sent = _time(payload.get('timestamp'), milliseconds=True)
        kind = 'reverse_order_line' if reverse else 'order_line_status'
        extra = dict(site=site, order_line_id=line, reverse_order_id=reverse, reverse_order_line_id=reverse_line)
        identity = [shop, site, kind, order, line, reverse, reverse_line, data.get('order_status'), at.isoformat()]
    elif platform == 'tiktok':
        if type(payload.get('type')) is not int or payload['type'] != 1:
            raise ValueError('Unsupported event')
        shop, order = _text(payload.get('shop_id')), _text(data.get('order_id'))
        at, sent = _time(data.get('update_time')), _time(payload.get('timestamp'))
        kind, extra = 'order_status', {}
        notification = payload.get('tts_notification_id')
        identity = [shop, _text(notification)] if notification else [shop, order, data.get('order_status'), at.isoformat()]
    else:
        raise ValueError('Unsupported platform')
    status = _text(data.get('order_status'), 80)
    return dict(shop_id=shop, order_sn=order, status=status, kind=kind, event_at=at, sent_at=sent,
                event_key=hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest(),
                body_hash=hashlib.sha256(body).hexdigest(), **extra)


@csrf_exempt
@require_POST
def receive(request, config_id, platform):
    if len(request.body) > 65536:
        return HttpResponse(status=413)
    config = PlatformIntegrationConfig.objects.filter(pk=config_id, platform=platform,
        status__in=('active', 'verified')).first()
    options = (config.platform_config or {}) if config else {}
    if (not config or marketplace_authorization_api_type(config) != 'marketplace'
            or options.get('order_push_enabled') is not True
            or not str(options.get('order_push_callback_url', '')).startswith('https://')
            or not options.get('app_key')):
        return HttpResponse(status=404)
    try:
        secret = get_custody_backend().retrieve_secret(config.credential_id or options.get('app_secret_reference'))
    except CustodyError:
        return HttpResponse(status=503)
    if not verify_signature(options['app_key'], request.body, secret, request.headers.get('Authorization', '')):
        return HttpResponse(status=401)
    try:
        data = parse_event(platform, request.body)
    except (ValueError, TypeError, UnicodeError, OverflowError, OSError):
        return HttpResponse(status=400)
    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk)
        if (locked.status not in ('active', 'verified') or locked.platform_config != config.platform_config
                or locked.credential_id != config.credential_id):
            return HttpResponse(status=409)
        accounts = MarketplaceStoreAuthorization.objects.select_for_update().filter(
            tenant_id=config.tenant_id, integration_config=config, platform=platform,
            platform_store_id=data['shop_id'], status='active')
        if platform == 'lazada':
            accounts = accounts.filter(region=data['site'].split('_')[1].upper())
        matches = list(accounts[:2])
        if len(matches) != 1 or (matches[0].expires_at and matches[0].expires_at <= timezone.now()):
            return HttpResponse(status=403)
        event, created = WebhookEvent.objects.get_or_create(
            tenant_id=config.tenant_id, platform=platform, event_id=data['event_key'], defaults={
                'event_type': platform + '.' + data['kind'],
                'external_shop_id': data['site'] + ':' + data['shop_id'] if platform == 'lazada' else data['shop_id'],
                'external_order_id': data['order_sn'], 'order_status': data['status'],
                'event_at': data['event_at'], 'signature_status': 'valid', 'payload_hash': data['body_hash'],
                'processing_status': 'processed', 'processed_at': timezone.now()})
        if created:
            archive_webhook_payload(event, {**data, 'event_at': data['event_at'].isoformat(),
                'sent_at': data['sent_at'].isoformat(), 'store_id': matches[0].store_id})
    return HttpResponse(status=200)
