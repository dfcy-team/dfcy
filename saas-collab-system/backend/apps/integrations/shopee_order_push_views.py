"""Direct official Shopee push ingress; no developer gateway transport."""
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .custody import CustodyError, get_custody_backend
from .models import MarketplaceStoreAuthorization, PlatformIntegrationConfig, WebhookEvent, marketplace_authorization_api_type
from .raw_services import archive_webhook_payload
from .shopee_order_events import parse_status_event, verify_signature


def _active_account(config, shop_id):
    account = MarketplaceStoreAuthorization.objects.filter(
        tenant_id=config.tenant_id, integration_config=config, platform='shopee',
        platform_store_id=shop_id, status='active',
    ).first()
    if account and (not account.expires_at or account.expires_at > timezone.now()):
        return account
    return None


@csrf_exempt
@require_POST
def receive(request, config_id):
    if len(request.body) > 65536:
        return HttpResponse(status=413)
    config = PlatformIntegrationConfig.objects.filter(
        pk=config_id, platform='shopee', status__in=('active', 'verified'),
    ).first()
    options = (config.platform_config or {}) if config else {}
    callback_url = options.get('order_push_callback_url', '')
    if not config or marketplace_authorization_api_type(config) != 'marketplace' or options.get('order_push_enabled') is not True or not callback_url:
        return HttpResponse(status=404)
    try:
        reference = config.credential_id or options.get('app_secret_reference')
        key = get_custody_backend().retrieve_secret(reference)
    except CustodyError:
        return HttpResponse(status=503)
    if not verify_signature(callback_url, request.body, key, request.headers.get('Authorization', '')):
        return HttpResponse(status=401)
    try:
        data = parse_status_event(request.body)
    except (ValueError, UnicodeError, OverflowError):
        return HttpResponse(status=400)
    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk)
        if locked.status not in ('active', 'verified') or locked.platform_config != config.platform_config or locked.credential_id != config.credential_id:
            return HttpResponse(status=409)
        account = _active_account(config, data['shop_id'])
        if account is None:
            return HttpResponse(status=403)
        event, created = WebhookEvent.objects.get_or_create(
            tenant_id=config.tenant_id, platform='shopee', event_id=data['event_key'],
            defaults={'event_type': 'shopee.order_status:' + data['shop_id'],
                      'external_shop_id': data['shop_id'], 'external_order_id': data['order_sn'],
                      'order_status': data['status'], 'completed_scenario': data['completed_scenario'],
                      'event_at': data['event_at'],
                      'signature_status': 'valid', 'payload_hash': data['body_hash'],
                      'processing_status': 'processed', 'processed_at': timezone.now()},
        )
        if created:
            # Persist only the signed event fields needed for the order log.
            archive_webhook_payload(event, {
                **data, 'event_at': data['event_at'].isoformat(), 'sent_at': data['sent_at'].isoformat(),
                'store_id': account.store_id,
            })
    # Shopee requires a 2xx response with an empty body, after durable persistence.
    return HttpResponse(status=204)

