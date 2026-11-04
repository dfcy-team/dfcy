import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.integrations.models import SyncRawEnvelope
from apps.sales_management.order_item_prices import enrich_item_prices


class Command(BaseCommand):
    help = 'Attach saved provider order/escrow item prices to existing orders; no provider calls or sales fact changes.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)
        parser.add_argument('--store', action='append', default=[])
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        actor = CustomUser.objects.filter(username=options['actor'], is_active=True, is_superuser=True).first()
        if actor is None:
            raise CommandError('商品价格回填需要明确指定活动超级管理员。')
        rows = SyncRawEnvelope.objects.filter(tenant_id=actor.tenant_id, store__tenant_id=actor.tenant_id,
            platform__in=['shopee', 'lazada']).filter(Q(endpoint__contains='get_order_detail') |
            Q(endpoint__contains='order/items/get') | Q(endpoint__contains='get_escrow_detail'))
        if options['store']:
            rows = rows.filter(store__code__in=options['store'])
        ids = list(rows.order_by('-pk').values_list('pk', flat=True))
        summary = Counter(envelopes=len(ids))
        for pk in ids:
            envelope = rows.select_related('store__platform').get(pk=pk)
            summary.update(enrich_item_prices(envelope, save=options['apply']))
        result = {**summary, 'applied': options['apply'], 'provider_calls': 0,
            'quantities_changed': 0, 'order_totals_changed': 0, 'stored_line_totals_changed': 0}
        if options['apply'] and summary['items_updated']:
            OperationLog.objects.create(tenant_id=actor.tenant_id, user=actor, module='sales_management',
                object_type='SalesOrderItem', object_id='api-price-backfill', action='order_item_prices_backfilled',
                after_data=result)
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
