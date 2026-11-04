"""Conservative, transactional import of verified internal read-only snapshots.

No platform calls, credential changes, updates to existing facts or source-PK reuse.
Conflicting rows remain in the identity registry for explicit reconciliation.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU
from .business_sync_models import BusinessSyncSource, BusinessSyncBatch, BusinessSyncIdentity
from .models import PlatformFinanceTransaction
from .contracts import _reject_credentials

MODELS = {'sales_orders': SalesOrder, 'sales_order_items': SalesOrderItem,
          'finance_transactions': PlatformFinanceTransaction}
FIELDS = {
    'sales_orders': ('external_order_id region raw_status normalized_status created_at_utc updated_at_utc '
                     'paid_at_utc delivered_at_utc cancelled_at_utc completed_at_utc business_date currency '
                     'subtotal_amount seller_discount_amount platform_discount_amount shipping_amount tax_amount order_total_amount').split(),
    'sales_order_items': ('external_line_id platform_product_id platform_variant_id seller_sku item_name_snapshot '
                          'variation_snapshot quantity original_unit_price sale_unit_price discount_amount tax_amount '
                          'line_total_amount currency raw_line_status').split(),
    'finance_transactions': ('platform external_transaction_id external_order_id external_order_item_id seller_sku '
                             'platform_variant_id raw_fee_name fee_code fee_category raw_amount signed_amount currency '
                             'occurred_at_utc business_date').split(),
}
MONEY = {'sales_orders': 'order_total_amount', 'sales_order_items': 'line_total_amount',
         'finance_transactions': 'signed_amount'}
VERSION = 'internal-readonly.v1'


def canonical(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f') if value else '0'
    if isinstance(value, datetime):
        return value.astimezone(datetime_timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def projection(resource, row):
    result = {}
    for key in FIELDS[resource]:
        value = row.get(key)
        if key.endswith('_amount') or key in {'raw_amount', 'signed_amount', 'original_unit_price', 'sale_unit_price'}:
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValidationError('Non-finite snapshot amount.')
        elif key.endswith('_utc') and value is not None:
            value = parse_datetime(str(value))
            if value is None or timezone.is_naive(value):
                raise ValidationError('Snapshot timestamps must be timezone-aware.')
        elif key == 'business_date':
            value = date.fromisoformat(str(value))
        result[key] = value
    return result


def fingerprint(resource, values):
    body = {key: canonical(values[key]) for key in FIELDS[resource]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_fingerprint(resource, row, values):
    relations = {k: row.get(k) for k in ('store_id', 'platform_id', 'sales_order_id', 'sales_order_item_id')}
    return hashlib.sha256((fingerprint(resource, values) + json.dumps(relations, sort_keys=True)).encode()).hexdigest()


def verify_snapshot(path, origin):
    path = Path(path)
    meta = json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    if (meta.get('source') != origin or meta.get('complete') is not True or meta.get('sampled')
            or meta.get('full_pagination') is not True or meta.get('identifiers') != 'original_business_identifiers'
            or path.stat().st_size > 128 * 1024 * 1024):
        raise ValidationError('Snapshot is incomplete, masked or from a different source.')
    digest = hashlib.sha256()
    rows, previous = [], 0
    with path.open('rb') as stream:
        for line in stream:
            if len(line) > 1024 * 1024:
                raise ValidationError('Snapshot row exceeds its bound.')
            digest.update(line)
            row = json.loads(line)
            _reject_credentials(row)
            if type(row.get('id')) is not int or row['id'] <= previous:
                raise ValidationError('Source identities must be positive, unique and ascending.')
            previous = row['id']
            rows.append(row)
            if len(rows) > 100000:
                raise ValidationError('Narrow the snapshot date window.')
    if digest.hexdigest() != meta['sha256'] or len(rows) != meta['rows']:
        raise ValidationError('Snapshot hash or row count does not match.')
    return meta, rows


def store_mapping(source, masters):
    platforms = {r['id']: r['platform_type'] for r in masters['platforms']}
    local = defaultdict(list)
    for store in StoreMaster.objects.filter(tenant_id=source.tenant_id).select_related('platform'):
        local[(store.code, store.platform.platform_type, store.country_code)].append(store)
    result = {}
    for row in masters['stores']:
        matches = local[(row['code'], platforms[row['platform_id']], row['country_code'])]
        if len(matches) == 1:
            result[row['id']] = matches[0]
    return result


def _same(resource, obj, values):
    return all(canonical(getattr(obj, key)) == canonical(values[key]) for key in FIELDS[resource])


def _key(resource, row):
    if resource == 'sales_orders':
        return row['store_id'], row['external_order_id']
    if resource == 'sales_order_items':
        return row['sales_order_id'], row['external_line_id']
    return tuple(row.get(k) for k in ('store_id', 'external_transaction_id', 'external_order_id',
                                     'external_order_item_id', 'raw_fee_name', 'occurred_at_utc', 'currency'))


def _parent(source, row):
    identity = BusinessSyncIdentity.objects.filter(
        source=source, resource='sales_orders', source_record_id=row['sales_order_id'],
        status__in=['created', 'adopted'], target_id__isnull=False).first()
    if identity:
        return SalesOrder.objects.filter(pk=identity.target_id, tenant_id=source.tenant_id).first()
    return None


def _sku_mapping(source, masters):
    local = defaultdict(set)
    records = {}
    for sku in ProductSKU.objects.filter(tenant_id=source.tenant_id).only('id', 'spu_id', 'sku_code', 'legacy_sku_code'):
        records[sku.pk] = sku
        for code in (sku.sku_code, sku.legacy_sku_code):
            if code:
                local[code].add(sku.pk)
    mapping = {}
    for row in masters.get('product_details', []):
        matches = set().union(*(local[code] for code in (row.get('sku_code'), row.get('legacy_sku_code')) if code))
        if len(matches) == 1:
            mapping[row['id']] = records[next(iter(matches))]
    return {'source_ids': mapping, 'codes': {code: records[next(iter(ids))] for code, ids in local.items() if len(ids) == 1}}


def _match_sku(row, mapping):
    if row.get('internal_sku_id') is not None:
        return mapping['source_ids'].get(row['internal_sku_id'])
    code = row.get('seller_sku')
    if not code:
        return None
    return mapping['codes'].get(code)


@transaction.atomic
def import_snapshot(*, source, actor, path, masters, apply=False):
    source = BusinessSyncSource.objects.select_for_update().get(pk=source.pk)
    if not actor.is_active or not actor.is_superuser or actor.tenant_id != source.tenant_id or not source.is_enabled:
        raise PermissionDenied('An active same-tenant administrator and enabled internal source are required.')
    meta, rows = verify_snapshot(path, source.origin)
    resource = meta['resource']
    if resource not in MODELS:
        raise ValidationError('Unsupported business snapshot resource.')
    first, last = [date.fromisoformat(v) for v in meta['window'].split('_')]
    if not date(2026, 7, 1) <= first <= last <= date(2026, 9, 30) or (last - first).days > 30:
        raise ValidationError('Snapshot is outside the approved Q3 batch scope.')
    stores = store_mapping(source, masters)
    sku_mapping = _sku_mapping(source, masters) if resource == 'sales_order_items' else {}
    duplicates = Counter(_key(resource, row) for row in rows)
    model = MODELS[resource]
    batch, _ = BusinessSyncBatch.objects.get_or_create(
        source=source, resource=resource, date_from=first, date_to=last, snapshot_hash=meta['sha256'],
        defaults={'tenant_id': source.tenant_id})
    counts, reasons, quality = Counter(), Counter(), Counter()
    amounts = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        values = projection(resource, row)
        row_hash = source_fingerprint(resource, row, values)
        existing = BusinessSyncIdentity.objects.filter(source=source, resource=resource, source_record_id=row['id']).first()
        status, reason, target = 'pending', '', None
        if existing and existing.target_id:
            scope = {'sales_order__tenant_id': source.tenant_id} if resource == 'sales_order_items' else {'tenant_id': source.tenant_id}
            target = model.objects.filter(pk=existing.target_id, **scope).first()
            if existing.payload_hash == row_hash and target and _same(resource, target, values):
                status = 'unchanged'
                sku = _match_sku(row, sku_mapping) if resource == 'sales_order_items' and not target.internal_sku_id else None
                if (sku and existing.status == 'created' and not target.internal_sku_id
                        and target.internal_spu_id in (None, sku.spu_id)
                        and target.sales_order.internal_sync_batch_id
                        and target.sales_order.internal_sync_batch.source_id == source.pk):
                    target.internal_sku_id, target.internal_spu_id = sku.pk, sku.spu_id
                    target.save(update_fields=['internal_sku', 'internal_spu'])
                    quality['sku_links_added'] += 1
            else:
                reason = 'source_or_local_fact_changed'
        elif duplicates[_key(resource, row)] > 1:
            reason = 'duplicate_source_business_key'
        else:
            parent = _parent(source, row) if resource == 'sales_order_items' else None
            store = parent.store if parent else stores.get(row.get('store_id'))
            if not store:
                reason = 'order_dependency_unmapped' if resource == 'sales_order_items' else 'store_unmapped'
            elif resource == 'sales_order_items' and not first <= parent.business_date <= last:
                raise ValidationError('Source returned an item whose order is outside the requested window.')
            elif resource != 'sales_order_items' and not first <= values['business_date'] <= last:
                raise ValidationError('Source returned a fact outside the requested date window.')
            elif resource == 'finance_transactions' and (row['platform'] != store.platform.platform_type):
                raise ValidationError('Source store and financial platform disagree.')
            elif resource == 'finance_transactions' and not (row['external_transaction_id'] or row['external_order_id']):
                reason = 'no_reliable_existing_business_key'
            else:
                if resource == 'sales_orders':
                    query = dict(tenant_id=source.tenant_id, store=store, external_order_id=row['external_order_id'])
                elif resource == 'sales_order_items':
                    query = dict(sales_order=parent, external_line_id=row['external_line_id'])
                else:
                    query = {k: row[k] for k in ('external_transaction_id', 'external_order_id', 'external_order_item_id', 'raw_fee_name')}
                    query.update(tenant_id=source.tenant_id, store=store)
                matches = list(model.objects.select_for_update().filter(**query)[:2])
                if matches:
                    if len(matches) == 1 and _same(resource, matches[0], values):
                        bound = BusinessSyncIdentity.objects.filter(source=source, resource=resource, target_id=matches[0].pk).exists()
                        if bound:
                            reason = 'target_already_bound_to_another_source_row'
                        else:
                            status, target = 'adopted', matches[0]
                    else:
                        reason = 'existing_business_key_conflict'
                else:
                    kwargs = dict(values)
                    if resource == 'sales_orders':
                        kwargs.update(tenant_id=source.tenant_id, store=store, platform=store.platform,
                                      internal_sync_batch=batch, status_mapping_version=VERSION, payload_hash=row_hash,
                                      source_details={'internal_sync_source': source.code, 'source_id': row['id']})
                    elif resource == 'sales_order_items':
                        # Match local SKU only by an exact unique seller code; never reuse source SKU PKs.
                        sku = _match_sku(row, sku_mapping)
                        kwargs.update(sales_order=parent, internal_sku=sku, internal_spu_id=sku.spu_id if sku else None,
                                      source_details={'internal_sync_source': source.code, 'source_id': row['id'],
                                                      'source_internal_sku_id': row.get('internal_sku_id'),
                                                      'source_internal_spu_id': row.get('internal_spu_id')})
                    else:
                        orders = list(SalesOrder.objects.filter(tenant_id=source.tenant_id, store=store,
                                                               external_order_id=row['external_order_id'])[:2])
                        orders = [o for o in orders if o.external_order_id == row['external_order_id']]
                        linked_parent = _parent(source, row) if row.get('sales_order_id') else None
                        if linked_parent and (linked_parent.store_id != store.pk or linked_parent.external_order_id != row['external_order_id']):
                            raise ValidationError('Financial parent identity disagrees with the source order number or store.')
                        order = linked_parent or (orders[0] if len(orders) == 1 else None)
                        items = list(order.items.filter(external_line_id=row['external_order_item_id'])[:2]) if order and row['external_order_item_id'] else []
                        items = [i for i in items if i.external_line_id == row['external_order_item_id']]
                        item = items[0] if len(items) == 1 else None
                        kwargs.update(tenant_id=source.tenant_id, store=store, internal_sync_batch=batch,
                                      source_key=f'internal:{source.pk}:{row["id"]}', payload_hash=row_hash,
                                      normalization_version=VERSION, sales_order=order, sales_order_item=item,
                                      match_status='matched' if item else 'order_only' if order else 'unmatched')
                    target = model(**kwargs)
                    target.full_clean()
                    target.save()
                    status = 'created'
        counts[status] += 1
        if reason:
            reasons[reason] += 1
        if target and status != 'pending':
            if resource == 'sales_order_items' and not target.internal_sku_id:
                quality['items_without_unique_local_sku'] += 1
            if resource == 'finance_transactions' and target.match_status != 'matched':
                quality['finance_' + target.match_status] += 1
        currency = row['currency']
        amounts[currency]['source'] += Decimal(str(row[MONEY[resource]]))
        amounts[currency][status] += Decimal(str(row[MONEY[resource]]))
        if status != 'unchanged' and not (existing and existing.target_id):
            BusinessSyncIdentity.objects.update_or_create(
                source=source, resource=resource, source_record_id=row['id'],
                defaults=dict(batch=batch, payload_hash=row_hash, target_id=target.pk if target else None,
                              status=status, reason=reason, pending_payload=row if reason else {}))
        elif reason and existing:
            existing.reason, existing.pending_payload = reason, row
            existing.save(update_fields=['reason', 'pending_payload'])
    accounting = {'rows': len(rows), 'counts': dict(counts), 'pending_reasons': dict(reasons), 'quality': dict(quality),
                  'amounts': {c: {k: str(v) for k, v in values.items()} for c, values in amounts.items()}}
    if sum(counts.values()) != len(rows):
        raise ValidationError('Import accounting does not balance.')
    for currency, sums in amounts.items():
        if sums['source'] != sum((v for k, v in sums.items() if k != 'source'), Decimal(0)):
            raise ValidationError('Currency accounting does not balance.')
        expected = Decimal(meta['totals'][currency][MONEY[resource]])
        if sums['source'] != expected:
            raise ValidationError('Snapshot monetary totals do not match.')
    batch.accounting, batch.status, batch.completed_at = accounting, 'pending' if counts['pending'] else 'completed', timezone.now()
    batch.save(update_fields=['accounting', 'status', 'completed_at'])
    if not apply:
        transaction.set_rollback(True)
    return {'resource': resource, 'window': meta['window'], 'committed': apply, **accounting}
