"""Forward-only, store-scoped API withdrawals. Never writes business ledgers."""
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.readonly_clients import LazadaReadonlyClient, TikTokReadonlyClient
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import filter_store_authorizations
from .platform_wallet_collectors import CAPABILITIES, collect_lazada, collect_tiktok
from .platform_wallet_models import PlatformApiWithdrawal, PlatformWalletCursor, PlatformWalletSync
from .platform_wallet_scopes import scoped


def visible_stores(user, permission='finance.view'):
    return scoped(user, StoreMaster.objects.select_related('platform'), permission).order_by('platform__platform_type', 'code', 'pk')


def require_sync(user):
    if not user.is_active or user.user_type != 'internal' or not all(check_user_permission(user, code) for code in
        ('finance.view', 'finance.import', 'integrations.run_live_readonly')):
        raise PermissionDenied('同步须同时具备财务查看、财务导入和平台只读采集权限。')


def allowed_authorizations(user, store):
    require_sync(user)
    if not visible_stores(user).filter(pk=store.pk).exists() or not visible_stores(user, 'finance.import').filter(pk=store.pk).exists():
        raise PermissionDenied('店铺不在当前财务同步范围。')
    query = MarketplaceStoreAuthorization.objects.select_related('store', 'integration_config').filter(
        tenant=user.tenant, store=store, platform=store.platform.platform_type, status='active').filter(
            Q(integration_config__platform_config__api_type='marketplace') |
            Q(integration_config__platform_config__api_type__isnull=True))
    return filter_store_authorizations(user, query, 'integrations.run_live_readonly')


def persist(user, authorization, records, observed_at):
    """Allowlisted projection only, no raw accounts, request URLs or credentials."""
    if (authorization.tenant_id != user.tenant_id or authorization.store.tenant_id != user.tenant_id
            or authorization.integration_config.tenant_id != user.tenant_id):
        raise PermissionDenied('API资金来源不属于当前租户。')
    written = 0
    for row in records:
        candidate = PlatformApiWithdrawal(tenant=user.tenant, store=authorization.store,
                                          authorization=authorization, observed_at_utc=observed_at, **row)
        # Apply the same OR branches to store AND returned currency. A role
        # allowing USD in shop A must not permit PHP there via a role for B.
        if not record_allowed(user, authorization.store, row['currency'], 'finance.view') or not record_allowed(user, authorization.store, row['currency'], 'finance.import'):
            continue
        existing = PlatformApiWithdrawal.objects.select_for_update().filter(tenant=user.tenant,
            store=authorization.store, source_endpoint=row['source_endpoint'], external_id=row['external_id']).first()
        if existing and existing.observed_at_utc > observed_at:
            continue
        if existing:
            for field in row:
                setattr(existing, field, row[field])
            existing.observed_at_utc = observed_at
            existing.authorization = authorization
            existing.full_clean()
            existing.save()
        else:
            candidate.full_clean()
            candidate.save()
        written += 1
    return written


def record_allowed(user, store, currency, permission):
    # Use the real queryset scope compiler with an explicit currency.
    # This preserves each role's conjunction without manufacturing a DB row.
    from .platform_wallet_scopes import scoped_money_stores
    return scoped_money_stores(user, StoreMaster.objects.filter(pk=store.pk), permission, currency).exists()


def lazada_wallet_time_policy(authorization):
    policies = (authorization.integration_config.platform_config or {}).get('wallet_transaction_time_policies')
    policy = policies.get(str(authorization.store_id)) if isinstance(policies, dict) else None
    if not isinstance(policy, dict) or policy.get('source') != 'user_specified':
        raise ValidationError('Lazada账户交易尚未登记用户指定的时区口径。')
    try:
        return ZoneInfo(policy['timezone']), policy['source']
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValidationError('Lazada账户交易时区配置无效。') from None


def sync_store(sync, store, *, end, lease):
    user = sync.actor
    user.refresh_from_db()
    if sync.activated_at is None:
        raise ValidationError('同步尚未建立增量起点。')
    capability = CAPABILITIES.get(store.platform.platform_type, {'withdrawals': False})
    if not capability['withdrawals']:
        return {'store_id': store.pk, 'status': 'unsupported', 'error_code': 'CONTRACT_UNVERIFIED'}
    auths = list(allowed_authorizations(user, store).order_by('pk')[:2])
    if len(auths) != 1:
        raise ValidationError('店铺须有唯一有效的平台授权。')
    auth = auths[0]
    if auth.store.tenant_id != user.tenant_id or auth.integration_config.tenant_id != user.tenant_id:
        raise PermissionDenied('授权租户不一致。')
    if auth.expires_at and auth.expires_at <= end:
        raise ValidationError('授权已过期；不会自动刷新令牌。')
    cursor, _ = PlatformWalletCursor.objects.get_or_create(sync=sync, store=store)
    cursor.last_attempt_at = timezone.now()
    cursor.save(update_fields=['last_attempt_at'])
    # Re-read only data from activation onward. The 1-day overlap refreshes
    # recent states; older non-terminal records keep the window open.
    start = max(sync.activated_at, (cursor.watermark or sync.activated_at) - timedelta(days=1))
    pending = PlatformApiWithdrawal.objects.filter(tenant=user.tenant, store=store,
        occurred_at_utc__gte=sync.activated_at, raw_status__in=['PROCESSING', 'PENDING', 'INITIAL']).order_by('occurred_at_utc').first()
    if pending:
        start = min(start, pending.occurred_at_utc)
    if end <= start or int(end.timestamp()) <= int(start.timestamp()):
        return {'store_id': store.pk, 'status': 'not_due', 'count': 0}
    if store.platform.platform_type == 'lazada':
        client = LazadaReadonlyClient(auth.integration_config, authorization=auth)
        # An explicit, store-scoped business policy is not an official API
        # timezone guarantee and must not alter the shop's archive timezone.
        client.wallet_transaction_timezone, client.wallet_transaction_time_source = lazada_wallet_time_policy(auth)
        collector = collect_lazada
    else:
        client = TikTokReadonlyClient(auth.integration_config, authorization=auth)
        collector = collect_tiktok
    client.preflight()
    # Chunk time windows to bound provider requests without advancing the
    # watermark until every chunk has passed its completeness checks.
    rows, warning, window = [], 0, start
    while window < end:
        stop = min(end, window + timedelta(days=1))
        result, info = collector(client, window, stop)
        rows.extend(result)
        warning += info.get('reported_count_difference', 0)
        window = stop
    with transaction.atomic():
        current = PlatformWalletSync.objects.select_for_update().get(pk=sync.pk)
        if current.lease != lease or current.running_until is None or current.running_until <= timezone.now():
            raise ValidationError('同步租约已失效，未保存数据。')
        user.refresh_from_db()
        if current.actor_id != user.pk or current.tenant_id != user.tenant_id or not allowed_authorizations(user, store).filter(pk=auth.pk).exists():
            raise PermissionDenied('同步期间权限发生变化。')
        count = persist(user, auth, rows, end)
        cursor.watermark, cursor.last_success_at, cursor.last_error_code = end, timezone.now(), ''
        cursor.save(update_fields=['watermark', 'last_success_at', 'last_error_code'])
    return {'store_id': store.pk, 'status': 'succeeded', 'count': count, 'reported_count_difference': warning}
