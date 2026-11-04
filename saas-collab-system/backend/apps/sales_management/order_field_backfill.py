"""Offline, tenant-scoped enrichment of existing orders from integrity-checked RAW."""
import hashlib
import json
from collections import Counter
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Prefetch
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from apps.audit.models import OperationLog
from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.integrations.adapters import MarketplaceOrderAdapter, LazadaOrderAdapter
from apps.integrations.models import SyncRawEnvelope
from apps.integrations.order_field_mapping import ORDER_COLUMNS, LINE_COLUMNS, apply_order_observations
from apps.integrations.raw_services import payload_digest


def fingerprint(order):
    value = {key: getattr(order, key) for key in (*ORDER_COLUMNS, 'updated_at_utc', 'currency', 'order_total_amount', 'source_details')}
    value['items'] = [{key: getattr(line, key) for key in (*LINE_COLUMNS, 'pk', 'external_line_id',
        'platform_product_id', 'platform_variant_id', 'seller_sku', 'quantity', 'line_total_amount', 'source_details')}
        for line in order.items.all()]
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=True).encode()).hexdigest()


def build_plan(actor):
    orders = {(order.store_id, order.external_order_id): order for order in SalesOrder.objects.filter(
        tenant=actor.tenant).select_related('store__platform').prefetch_related('items').order_by('pk')}
    rows = SyncRawEnvelope.objects.filter(tenant=actor.tenant, store__isnull=False,
        sync_run__tenant=actor.tenant, sync_run__sync_job__resource_type='sales_order',
        platform__in=['shopee', 'lazada', 'tiktok'])
    # Select narrow IDs first: sorting large JSON values can exceed MySQL's
    # sort buffer even with LIMIT. No server configuration change is needed.
    ids = list(rows.order_by('-pk').values_list('pk', flat=True))
    summary = Counter(envelopes=len(ids))
    plan, seen = [], set()
    for pk in ids:
        envelope = rows.select_related('store__platform', 'sync_run__sync_job__integration_config').get(pk=pk)
        if payload_digest(envelope.payload) != envelope.payload_hash:
            raise ValidationError('原始响应完整性校验失败，未进行回填。')
        if (envelope.store.tenant_id != actor.tenant_id or envelope.store.platform.platform_type != envelope.platform
                or envelope.sync_run.sync_job.integration_config.platform != envelope.platform):
            summary['scope_mismatch'] += 1
            continue
        adapter = (LazadaOrderAdapter if envelope.platform == 'lazada' else MarketplaceOrderAdapter)(
            SimpleNamespace(platform=envelope.platform, platform_config={}))
        adapter.authorization = SimpleNamespace(store=envelope.store, region=envelope.store.country_code)
        # The RAW normalizer is pure. Do not call validate_configuration,
        # replay_raw_envelope or any client: those may access external services.
        for raw in envelope.payload.get('records') or []:
            if not isinstance(raw, dict):
                summary['invalid_record'] += 1
                continue
            external = str(raw.get('order_sn') if envelope.platform == 'shopee' else raw.get('order_id') if envelope.platform == 'lazada' else raw.get('id'))
            key = (envelope.store_id, external)
            order = orders.get(key)
            if order is None:
                summary['missing_local_order'] += 1
                continue
            if key in seen:
                summary['duplicate_snapshot'] += 1
                continue
            try:
                # Bypass the live adapter's retention wrapper for already
                # retained local facts. This never creates or resyncs an order.
                normalize = type(adapter).normalize_record.__wrapped__
                payload = normalize(adapter, raw)
            except Exception:
                summary['invalid_record'] += 1
                continue
            source_time = parse_datetime(payload['source_updated_at'])
            if source_time != order.updated_at_utc or payload['currency'] != order.currency:
                summary['different_snapshot'] += 1
                continue
            seen.add(key)
            before = fingerprint(order)
            result = apply_order_observations(order, payload, save=False)
            summary['matched_orders'] += 1
            summary['unmatched_items'] += result['unmatched_items']
            if result['order_fields'] or result['item_fields']:
                plan.append({'order_id': order.pk, 'envelope_id': pk, 'raw_hash': envelope.payload_hash,
                             'before': before, 'after': fingerprint(order), 'payload': payload})
                summary['orders_to_update'] += 1
                summary['order_fields_to_update'] += result['order_fields']
                summary['item_fields_to_update'] += result['item_fields']
    digest = hashlib.sha256(json.dumps([{key: item[key] for key in ('order_id', 'envelope_id', 'raw_hash', 'before', 'after')}
        for item in plan], sort_keys=True).encode()).hexdigest()
    return plan, {**summary, 'plan_sha256': digest, 'provider_calls': 0, 'creates_orders': False}


@transaction.atomic
def apply_plan(actor, plan):
    updated = Counter()
    for item in plan:
        order = SalesOrder.objects.select_for_update().prefetch_related(
            Prefetch('items', queryset=SalesOrderItem.objects.select_for_update().order_by('pk'))
        ).get(pk=item['order_id'], tenant=actor.tenant)
        if fingerprint(order) != item['before']:
            raise ValidationError('本地订单已变化，本次回填已回滚，请重新预览。')
        result = apply_order_observations(order, item['payload'])
        if fingerprint(order) != item['after']:
            raise ValidationError('回填结果与预览不一致，本次操作已回滚。')
        OperationLog.objects.create(tenant=actor.tenant, user=actor, module='sales_management',
            object_type='SalesOrder', object_id=str(order.pk), action='order_fields_backfilled',
            before_data={'state_hash': item['before']},
            after_data={'state_hash': item['after'], 'raw_envelope_id': item['envelope_id'],
                        'raw_hash': item['raw_hash'], 'changed_fields': result})
        updated['orders_updated'] += 1
        updated['order_fields_updated'] += result['order_fields']
        updated['item_fields_updated'] += result['item_fields']
    return {**updated, 'provider_calls': 0, 'orders_created': 0, 'quantities_changed': 0, 'order_totals_changed': 0}
