import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.commerce.models import SalesOrder
from apps.integrations.models import MarketplaceStoreAuthorization, marketplace_authorization_api_type
from apps.integrations.net_guard import PlatformHttpClient
from apps.integrations.readonly_clients import ShopeeReadonlyClient
from apps.integrations.shopee_logistics import collect_order_logistics, collect_return_logistics
from apps.permissions.services import check_user_permission
from apps.sales_management.logistics_backfill import require_actor, settlement_plan, start_batch, save_snapshot, business_hash
from apps.sales_management.scopes import filter_sales_queryset
from apps.masterdata.models import StoreMaster


class Command(BaseCommand):
    help = 'One-off logistics-only backfill for a frozen Shopee settlement month; never enable jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)
        parser.add_argument('--store', default='SPKJ1PH1')
        parser.add_argument('--month', default='2026-09')
        parser.add_argument('--batch-id', type=int)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--returns-all', action='store_true')

    def emit(self, value):
        self.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True))
        self.stdout.flush()

    def handle(self, *args, **options):
        actor = CustomUser.objects.get(username=options['actor'], is_active=True)
        require_actor(actor)
        if options['limit'] < 0:
            raise CommandError('limit must be nonnegative.')
        batch = None
        if options['batch_id']:
            batch = OperationLog.objects.get(pk=options['batch_id'], tenant=actor.tenant, user=actor,
                action='logistics_backfill_started', object_type='SalesOrderLogisticsBackfill')
            plan = batch.after_data
            if plan['store_code'] != options['store'] or plan['month'] != options['month']:
                raise CommandError('Batch store/month mismatch.')
        else:
            plan = settlement_plan(actor, options['store'], options['month'])
        self.emit({key: value for key, value in plan.items() if key != 'orders'})
        if not options['apply']:
            return
        auths = [row for row in MarketplaceStoreAuthorization.objects.filter(tenant=actor.tenant,
            store_id=plan['store_id'], platform='shopee', status='active').select_related('integration_config', 'store')
            if marketplace_authorization_api_type(row.integration_config) == 'marketplace']
        if len(auths) != 1:
            raise CommandError('Exactly one active marketplace authorization is required.')
        auth = auths[0]
        if auth.expires_at and auth.expires_at <= timezone.now():
            raise CommandError('SHOPEE_TOKEN_REFRESH_REQUIRED')
        client = ShopeeReadonlyClient(auth.integration_config, auth, http_client=PlatformHttpClient(max_retries=0))
        client.resource_type = 'sales_order'
        client.preflight()
        batch = batch or start_batch(actor, plan)
        self.emit({'batch_id': batch.id, 'target_orders': len(plan['orders'])})
        saved_ids = {order_id for order_id, return_id in OperationLog.objects.filter(tenant=actor.tenant,
            action='logistics_snapshot_saved', after_data__batch_id=batch.id).values_list('object_id', 'after_data__return_id')
            if return_id is None}
        pending = [row for row in plan['orders'] if str(row['id']) not in saved_ids]
        if options['limit']:
            pending = pending[:options['limit']]
        counts = Counter(already_saved=len(saved_ids), requested=0, saved=0, failed=0)

        def collect(raw):
            close_old_connections()
            try:
                facts, _ = collect_order_logistics(client, raw)
                return raw['order_sn'], facts, None
            except Exception as exc:
                return raw['order_sn'], None, type(exc).__name__
            finally:
                close_old_connections()

        for offset in range(0, len(pending), 25):
            chunk = pending[offset:offset + 25]
            ids = [row['external_order_id'] for row in chunk]
            payload = client._request(client.ORDER_DETAIL_PATH,
                {'order_sn_list': ','.join(ids), 'response_optional_fields': client.ORDER_OPTIONAL_FIELDS})
            records = (payload.get('response') or {}).get('order_list') or []
            if sorted(row.get('order_sn') for row in records) != sorted(ids):
                raise CommandError('Order detail identity set mismatch; resume this batch after review.')
            with ThreadPoolExecutor(max_workers=3) as pool:
                for external_id, facts, error_type in pool.map(collect, records):
                    counts['requested'] += 1
                    if error_type or facts.get('status') != 'ok':
                        counts['failed'] += 1
                        self.emit({'order': external_id, 'status': 'not_saved', 'error_type': error_type,
                                   'query_status': facts.get('status') if facts else None})
                        continue
                    try:
                        outcome = save_snapshot(actor, batch, external_id, facts)
                        counts[outcome] += 1
                    except Exception as exc:
                        counts['failed'] += 1
                        self.emit({'order': external_id, 'status': 'not_saved', 'error_type': type(exc).__name__})
            self.emit({'batch_id': batch.id, 'forward_progress': dict(counts), 'target_orders': len(plan['orders'])})

        if options['returns_all']:
            if not check_user_permission(actor, 'sales_management.returns.view') or not filter_sales_queryset(
                    actor, 'sales_management.returns.view', StoreMaster.objects.filter(tenant=actor.tenant, pk=plan['store_id']),
                    {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'}).exists():
                raise CommandError('Return view permission is required.')
            client.resource_type = 'refund_return'
            targets = {row['external_order_id'] for row in plan['orders']}
            start = SalesOrder.objects.filter(tenant=actor.tenant,
                pk__in=[row['id'] for row in plan['orders']]).order_by('created_at_utc').first().created_at_utc
            end = timezone.now()
            returns = Counter(seen=0, in_scope=0, outside_scope=0, saved=0, already_saved=0, failed=0)
            seen = set()
            while start <= end:
                upper = min(end, start + timedelta(days=15) - timedelta(seconds=1))
                scope = {'time_from': int(start.timestamp()), 'time_to': int(upper.timestamp()), 'page_size': 4}
                cursor = ''
                while True:
                    page = client.fetch_returns(cursor, scope)
                    for raw in page.get('records') or []:
                        rid = raw.get('return_sn') or raw.get('return_id')
                        if not rid or rid in seen:
                            continue
                        seen.add(rid)
                        returns['seen'] += 1
                        external_id = raw.get('order_sn') or raw.get('order_id')
                        if external_id not in targets:
                            returns['outside_scope'] += 1
                            continue
                        returns['in_scope'] += 1
                        try:
                            facts, _ = collect_return_logistics(client, rid)
                            facts['order_sn'] = external_id
                            outcome = save_snapshot(actor, batch, external_id, facts, return_id=rid)
                            returns[outcome] += 1
                        except Exception as exc:
                            returns['failed'] += 1
                            self.emit({'return': rid, 'status': 'not_saved', 'error_type': type(exc).__name__})
                    self.emit({'batch_id': batch.id, 'returns_progress': dict(returns)})
                    next_cursor = page.get('next_cursor') or ''
                    if not next_cursor:
                        break
                    if next_cursor == cursor:
                        raise CommandError('Return pagination did not advance.')
                    cursor = next_cursor
                start = upper + timedelta(seconds=1)

        changed = [order.external_order_id for order in SalesOrder.objects.filter(tenant=actor.tenant,
            pk__in=[row['id'] for row in plan['orders']]).prefetch_related('items')
            if business_hash(order) != next(row['business_hash'] for row in plan['orders'] if row['id'] == order.id)]
        self.emit({'batch_id': batch.id, 'business_fields_changed': len(changed),
            'forward': dict(counts), 'warehouse_calls': 0, 'jobs_enabled': 0})
        if changed:
            raise CommandError('Business fields changed during this batch; inspect concurrent changes.')
