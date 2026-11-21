from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.commerce import country_decisions as domain
from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductCategory
from .decision_api import CountryDecisionAPI
from .inventory_queries import eligible_inventory_orders, latest_country_inventory, prefer_sales_order_time
from .scopes import filter_inventory_queryset, filter_sales_queryset
from .spu_inventory import summarize_variants


class CategoryQuery(serializers.Serializer):
    abc_grade = serializers.ChoiceField(choices=['', 'A', 'B', 'C', 'new', 'no_sales', 'unavailable'], default='')
    stocked_only = serializers.BooleanField(default=False)
    country_id = serializers.IntegerField(min_value=1, required=False)
    category_id = serializers.IntegerField(min_value=-1, required=False)
    category_ids = serializers.CharField(required=False, max_length=2000, allow_blank=True)
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    spu_id = serializers.IntegerField(min_value=1, required=False)
    sku_id = serializers.IntegerField(min_value=1, required=False)
    level = serializers.ChoiceField(choices=['category', 'spu', 'sku', 'stores', 'warehouses', 'unmapped'], default='category')
    days = serializers.ChoiceField(choices=[7, 15, 30], default=30)
    search = serializers.CharField(max_length=160, required=False, allow_blank=True, default='')
    offset = serializers.IntegerField(min_value=0, default=0)

    def validate_category_ids(self, raw):
        if not raw.strip():
            return set()
        parts = raw.split(',')
        if len(parts) > 100 or any(not part.isascii() or not part.isdecimal() or len(part) > 19 for part in parts):
            raise serializers.ValidationError('请选择最多 100 个有效类目。')
        values = {int(part) for part in parts}
        if any(value < 1 or value > 9223372036854775807 for value in values):
            raise serializers.ValidationError('类目编号必须为正数。')
        return values


def _source(actor, country, permissions):
    rows = latest_country_inventory(domain._country_inventory_source(actor, country, timezone.now()))
    rows = filter_inventory_queryset(actor, domain.INVENTORY, rows, permission_cache=permissions).filter(
        warehouse__status='active')
    mapped = domain.skus_for(actor, country, permissions).values('pk')
    return rows.filter(Q(internal_sku_id__isnull=True) | Q(internal_sku_id__in=mapped))


def _load_stock_facts(actor, country, permissions):
    source = _source(actor, country, permissions)
    rows = list(source.order_by().values(
        'id', 'site_code', 'internal_sku_id', 'source_sku', 'seller_sku', 'warehouse_id',
        'warehouse__name', 'on_hand_qty', 'available_qty', 'provided_quantity_fields',
        'source_run_id', 'source_run__status', 'source_run__failed_count'))
    aliases = Counter((row['warehouse_id'], row['source_sku']) for row in rows)
    mapped_aliases = Counter((row['warehouse_id'], row['internal_sku_id']) for row in rows
                             if row['internal_sku_id'] is not None)
    for row in rows:
        unique_mapping = (aliases[row['warehouse_id'], row['source_sku']] == 1
                          and (row['internal_sku_id'] is None
                               or mapped_aliases[row['warehouse_id'], row['internal_sku_id']] == 1))
        valid_batch = row['source_run__status'] == 'success' and not row['source_run__failed_count']
        provided = row['provided_quantity_fields'] or []
        row['available_known'] = (unique_mapping and valid_batch and 'available_qty' in provided
                                  and row['available_qty'] is not None and row['available_qty'] >= 0)
        row['on_hand_known'] = (unique_mapping and valid_batch and 'on_hand_qty' in provided
                                and row['on_hand_qty'] is not None and row['on_hand_qty'] >= 0)
    known_by_sku = defaultdict(list)
    for row in rows:
        if row['internal_sku_id'] is not None:
            known_by_sku[row['internal_sku_id']].append(row)
    inventory = {sku: (sum(f['available_qty'] for f in facts) if all(f['available_known'] for f in facts) else None)
                 for sku, facts in known_by_sku.items()}
    return rows, inventory


def stock_facts(actor, country, permissions):
    return _stock_context(actor, country, permissions)[0]


def _stock_context(actor, country, permissions):
    key = f'cloud-v518:v1:{actor.tenant_id}:{actor.pk}:{country.pk}:{domain.permission_signature(actor, permissions)}'
    return cache.get_or_set(key, lambda: _load_stock_facts(actor, country, permissions), 60)


def sales_facts(actor, country, days, permissions, sku_ids=None, *, by_store=False):
    if not by_store and sku_ids is not None:
        window = domain.sales_windows(actor, country, set(sku_ids), [days],
                                      permission_cache=permissions, inventory_only=True)[days]
        complete = window['coverage_complete'] and not window['unmapped'] and not window['bundle_composition_unverified']
        return [{'internal_sku_id': sku_id, 'units': units}
                for sku_id, units in window['units_by_sku'].items() if units > 0 or complete]
    stores = filter_sales_queryset(actor, domain.SALES,
        StoreMaster.objects.filter(tenant_id=actor.tenant_id, country_code__iexact=country.country_code,
                                   status='active'),
        {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'},
        permission_cache=permissions)
    groups = defaultdict(list)
    now = timezone.now()
    for pk, tz in stores.values_list('id', 'timezone'):
        try:
            groups[ZoneInfo(tz)].append(pk)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
    result = []
    for zone, store_ids in groups.items():
        end = now.astimezone(zone).date()
        upper = datetime.combine(end, time.min, zone)
        lower = datetime.combine(end - timedelta(days=days), time.min, zone)
        orders = SalesOrder.objects.filter(tenant_id=actor.tenant_id, store_id__in=store_ids,
            created_at_utc__gte=lower, created_at_utc__lt=upper, paid_at_utc__isnull=False, paid_at_utc__lt=upper,
            normalized_status__in=['confirmed', 'fulfilled', 'completed'], source_run__status='success',
            source_run__failed_count=0)
        orders = prefer_sales_order_time(orders)
        with eligible_inventory_orders(orders) as eligible:
            rows = SalesOrderItem.objects.filter(sales_order_id__in=eligible, internal_sku_id__isnull=False)
            if sku_ids is not None:
                rows = rows.filter(internal_sku_id__in=sku_ids)
            fields = (('internal_sku_id', 'sales_order__store_id', 'sales_order__store__name',
                       'sales_order__store__platform__platform_type', 'currency') if by_store else ('internal_sku_id',))
            result.extend(rows.order_by().values(*fields).annotate(units=Sum('quantity'), amount=Sum('line_total_amount')))
    return result


def _unmapped(actor, country, permissions, *, search, warehouse_id, offset):
    rows = _source(actor, country, permissions).filter(internal_sku_id__isnull=True).filter(Q(on_hand_qty__gt=0) | Q(available_qty__gt=0))
    if warehouse_id:
        rows = rows.filter(warehouse_id=warehouse_id)
    if search:
        rows = rows.filter(Q(source_sku__icontains=search) | Q(seller_sku__icontains=search))
    agg = rows.aggregate(available=Sum('available_qty'), on_hand=Sum('on_hand_qty'),
                         missing=Count('pk', filter=Q(available_qty__isnull=True)))
    count = rows.count()
    data = list(rows.order_by('warehouse_id', 'source_sku', 'pk').values('id','source_sku','seller_sku','warehouse_id','warehouse__name','on_hand_qty','available_qty')[offset:offset+20])
    return data, count, {'available': agg['available'] if not agg['missing'] else None, 'on_hand': agg['on_hand'], 'sku_count': count}


def totals(ids, stock, sales):
    inventory = [stock.get(pk) for pk in ids]
    units = [sales[pk] for pk in ids if pk in sales]
    return {'available': sum(inventory) if ids and all(value is not None for value in inventory) else None,
            'sales': sum(units) if units else None,
            'stock_coverage': sum(value is not None for value in inventory),
            'sales_coverage': len(units)}


class CategoryInventory(CountryDecisionAPI):
    def get(self, request):
        query = CategoryQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        q = query.validated_data
        actor = request.user
        permissions = getattr(request, '_permission_resolution_cache', {})
        countries = list(domain.countries_for(actor, permissions).values('id', 'name', 'country_code'))
        if 'country_id' not in q:
            return Response({'data': {'countries': countries, 'categories': list(ProductCategory.objects.filter(
                tenant_id=actor.tenant_id).order_by('level', 'code', 'id').values('id','parent_id','name')), 'results': [], 'count': 0}})
        country = domain.country_for(actor, q['country_id'], permissions)
        source, inventory = _stock_context(actor, country, permissions)
        all_source = source
        warehouses = sorted(
            {row['warehouse_id']: row['warehouse__name'] for row in source}.items(),
            key=lambda item: (item[1], item[0]),
        )
        warehouse_id = q.get('warehouse_id')
        if warehouse_id is not None:
            if not any(pk == warehouse_id for pk, _ in warehouses):
                raise NotFound('仓库不存在。')
        if q.get('category_id') == -1 or q['level'] == 'unmapped':
            unmapped, count, summary = _unmapped(actor, country, permissions, search=q['search'],
                warehouse_id=warehouse_id, offset=q['offset'])
            return Response({'data': {'countries': countries, 'warehouses': [{'id': pk,'name':name} for pk,name in warehouses],
                'level':'unmapped','summary':summary,'count':count,'results':unmapped,'offset':q['offset'],'limit':20}})
        snapshots = source
        if warehouse_id is not None:
            snapshots = [row for row in source if row['warehouse_id'] == warehouse_id]
            per_sku = defaultdict(list)
            for fact in snapshots:
                if fact['internal_sku_id'] is not None:
                    per_sku[fact['internal_sku_id']].append(fact)
            inventory = {sku: (sum(f['available_qty'] for f in facts) if all(f['available_known'] for f in facts) else None)
                         for sku, facts in per_sku.items()}
        stock = inventory
        catalog = domain.skus_for(actor, country, permissions).filter(
            pk__in={row['internal_sku_id'] for row in snapshots})
        if q['search']:
            from django.db.models import Q
            term = q['search']
            catalog = catalog.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term)
                | Q(product_name__icontains=term) | Q(spu__product_name__icontains=term)
                | Q(spu__spu_code__icontains=term) | Q(spu__legacy_spu_code__icontains=term)
                | Q(specification__icontains=term))
        categories = {row['id']: row for row in ProductCategory.objects.filter(
            tenant_id=actor.tenant_id).values('id', 'parent_id', 'name')}
        category_id = q.get('category_id')
        # DRF has already parsed category_ids into a set; do not split/reparse.
        selected = q.get('category_ids', set())
        if (category_id and category_id not in categories) or not selected <= categories.keys():
            raise NotFound('类目不存在。')
        descendants = {category_id} if category_id is not None else set()
        for _ in range(3):
            descendants.update(pk for pk, node in categories.items() if node['parent_id'] in descendants and node['parent_id'])
        if selected:
            selected_descendants = set(selected)
            for _ in range(3):
                selected_descendants.update(pk for pk, node in categories.items()
                                            if node['parent_id'] in selected_descendants and node['parent_id'])
            descendants = descendants & selected_descendants if category_id is not None else selected_descendants
        if category_id == -1:
            catalog = catalog.filter(spu__category_node_id__isnull=True)
        elif category_id == 0:
            # Explicit positive category selection cannot include uncategorized
            # products. Keep the intersection empty, not the unfiltered branch.
            catalog = catalog.none() if selected else catalog.filter(spu__category_node__isnull=True)
        elif category_id is not None or selected:
            catalog = catalog.filter(spu__category_node_id__in=descendants)
        if 'spu_id' in q:
            catalog = catalog.filter(spu_id=q['spu_id'])
        if 'sku_id' in q:
            catalog = catalog.filter(pk=q['sku_id'])
        from .abc_access import decorate_rows, filter_skus
        if q['stocked_only']:
            stocked_ids = {row['internal_sku_id'] for row in snapshots if row['internal_sku_id'] is not None
                           and ((row.get('on_hand_known') and (row.get('on_hand_qty') or 0) > 0)
                                or (row.get('available_known') and (row.get('available_qty') or 0) > 0))}
            catalog = catalog.filter(pk__in=stocked_ids)
        if q['abc_grade'] and q['level'] in {'spu', 'sku'} and not q.get('sku_id'):
            catalog = filter_skus(actor, country, catalog, q['abc_grade'],
                                  grouped=q['level'] == 'spu' or bool(q.get('spu_id')))
        products = list(catalog.order_by('sku_code', 'pk').values(
            'id', 'sku_code', 'legacy_sku_code', 'specification', 'product_name', 'image_url',
            'spu_id', 'spu__spu_code', 'spu__legacy_spu_code', 'spu__product_name', 'spu__category_node_id'))
        ids = {row['id'] for row in products}
        level = q['level']
        sku_scope = sha256(','.join(map(str, sorted(ids))).encode()).hexdigest()[:16]
        sales_key = f'cloud-v518:v1:{actor.tenant_id}:{actor.pk}:{country.pk}:{q["days"]}:{sku_scope}:{domain.permission_signature(actor, permissions)}'
        observations = cache.get_or_set(sales_key,
            lambda: sales_facts(actor, country, q['days'], permissions, ids), 120)
        # Detail levels retain the same scoped summary/coverage as normal rows.
        # Timezone groups may contain the same SKU.
        sales = defaultdict(int)
        for row in observations:
            sales[row['internal_sku_id']] += row['units']
        summary = {**totals(ids, stock, sales), 'sku_count': len(ids),
                   'spu_count': len({row['spu_id'] for row in products})}
        if level == 'warehouses':
            results = [{'id': row['warehouse_id'], 'name': row['warehouse__name'], 'available': row['available_qty'] if row['available_known'] else None}
                       for row in snapshots if row['internal_sku_id'] in ids] if q.get('sku_id') else []
        elif level == 'stores':
            results = sales_facts(actor, country, q['days'], permissions, ids, by_store=True) if ids and (q.get('spu_id') or q.get('sku_id')) else []
            results.sort(key=lambda row: (-row['units'], row['sales_order__store_id'], row['currency']))
        else:
            from apps.commerce.inventory_listing import linked_sku_ids
            linked_ids = linked_sku_ids(actor.tenant_id, country.country_code, ids)
            unlisted_stock = {item['internal_sku_id'] for item in snapshots
                              if item['internal_sku_id'] in ids
                              and item['internal_sku_id'] not in linked_ids
                              and ((item.get('on_hand_known') and (item.get('on_hand_qty') or 0) > 0)
                                   or (item.get('available_known') and (item.get('available_qty') or 0) > 0))
                              and not sales.get(item['internal_sku_id'], 0)}
            summary['unlisted_stock_sku_count'] = len(unlisted_stock)
            grouped = defaultdict(list)
            for row in products:
                if level == 'category':
                    node = row['spu__category_node_id']
                    if node == category_id and category_id is not None:
                        continue
                    for _ in range(3):
                        parent = categories.get(node, {}).get('parent_id')
                        if not parent or parent == category_id:
                            break
                        node = parent
                    key = node or 0
                else:
                    key = row['spu_id'] if level == 'spu' else row['id']
                grouped[key].append(row)
            results = []
            for key, items in grouped.items():
                first = items[0]
                values = totals({row['id'] for row in items}, stock, sales)
                item_ids = {row['id'] for row in items}
                values['unlisted_stock_sku_count'] = len(item_ids & unlisted_stock)
                if item_ids and item_ids.issubset(unlisted_stock):
                    values['sales'] = 0
                if level == 'sku':
                    values['platform_mapping_status'] = 'linked' if key in linked_ids else 'unlinked'
                    if key in unlisted_stock:
                        values['stock_sales_reason'] = '有库存，未关联本国家平台商品'
                        values['sales'] = 0
                if level == 'spu':
                    variant_rows = [{'id': item['id'], 'code': item['sku_code'], 'legacy': item['legacy_sku_code'],
                        'name': item['product_name'] or '', 'specification': item['specification'] or '',
                        'available': stock.get(item['id']), 'sales': sales.get(item['id']),
                        'image_preview_url': f'/api/internal/commerce/inventory/country-decisions/{country.pk}/skus/{item["id"]}/image/' if item['image_url'] else ''}
                        for item in items]
                    pictured = [item for item in variant_rows if item['image_preview_url']]
                    representative = next((item for item in pictured if (item['sales'] or 0) > 0), pictured[0] if pictured else {})
                    values.update(variants=variant_rows, image_preview_url=representative.get('image_preview_url',''),
                                  **summarize_variants(variant_rows, window_days=q['days']))
                if level == 'category':
                    name = categories.get(key, {}).get('name', '未分类')
                    has_children = any(row['spu__category_node_id'] != key for row in items) if key else False
                    values.update(has_children=has_children)
                    values['sales_complete'] = values['sales_coverage'] == len(items)
                elif level == 'spu':
                    name = first['spu__product_name']
                    values.update(code=first['spu__spu_code'], legacy=first['spu__legacy_spu_code'])
                else:
                    name = first['product_name'] or first['spu__product_name']
                    values.update(code=first['sku_code'], legacy=first['legacy_sku_code'], specification=first['specification'])
                if level == 'sku':
                    pictured = next((item for item in items if item['image_url']), None)
                    if pictured:
                        values['image_preview_url'] = (
                            f'/api/internal/commerce/inventory/country-decisions/{country.pk}/skus/{pictured["id"]}/image/'
                        )
                results.append({'id': key, 'name': name, 'sku_count': len(items),
                                'spu_count': len({row['spu_id'] for row in items}), **values})
            results.sort(key=lambda row: (row['id'] == 0, row['name'], row['id']))
            if level == 'category' and category_id is None and not selected and warehouse_id is None:
                unmapped_rows, unmapped_count, unmapped = _unmapped(
                    actor, country, permissions, search='', warehouse_id=None, offset=0)
                if unmapped_count:
                    results.append({'id': -1, 'name': '未映射商品库存', 'sku_count': unmapped_count,
                                    'spu_count': 0, 'available': unmapped['available'], 'sales': None,
                                    'sales_complete': False, 'has_children': False})
                    results.sort(key=lambda row: (row['id'] == 0, row['id'] == -1, row['name'], row['id']))
        offset = q['offset']
        page = results[offset:offset + 20]
        abc_meta = {}
        if level in {'sku', 'spu'}:
            if level == 'spu':
                for row in page:
                    row['spu_id'] = row['id']
            abc_meta = decorate_rows(actor, country, page)
        batch_metadata = [{'warehouse_id': wid, 'run_ids': sorted({row['source_run_id'] for row in all_source if row['warehouse_id']==wid and row['source_run_id']})} for wid,_ in warehouses]
        unmapped_totals = {'sku_count':0,'available':0,'on_hand':0}
        if 'category_id' not in q and warehouse_id is None:
            unmapped_totals = _unmapped(actor,country,permissions,search='',warehouse_id=None,offset=0)[2]
        return Response({'data': {'countries': countries, 'summary': summary, 'unmapped_summary': unmapped_totals,
                                  'inventory_batches': batch_metadata, 'level':level,'count': len(results),
                                  'abc_meta': abc_meta, 'results': page, 'offset': offset, 'limit': 20, 'categories': list(categories.values()),
                                  'warehouses': [{'id': pk, 'name': name} for pk, name in warehouses]}})


def operations_summary(actor, country, skus, days, permissions, *, snapshots=None):
    ids = set(skus.order_by().values_list('pk', flat=True))
    selection = sha256(','.join(map(str, sorted(ids))).encode()).hexdigest()
    key = f'operations-summary:cloud-v518:v1:{actor.tenant_id}:{actor.pk}:{country.pk}:{domain.permission_signature(actor, permissions)}:{selection}'
    if snapshots is None:
        snapshots = cache.get_or_set(key, lambda: stock_facts(actor, country, permissions), 60)
    # The scoped override may be a one-shot generator. Consume it once; an
    # explicit empty override must never fall back to a broader cached source.
    snapshots = list(snapshots)
    observations = cache.get_or_set(key + f':sales:{days}', lambda: sales_facts(actor, country, days, permissions, ids), 120)
    quantities = defaultdict(int)
    known, unknown = set(), set()
    for row in snapshots or []:
        pk = row['internal_sku_id']
        if pk not in ids:
            continue
        if row['available_qty'] is None or row.get('available_known') is False:
            unknown.add(pk)
        else:
            known.add(pk)
            quantities[pk] += row['available_qty']
    known -= unknown
    sold = {row['internal_sku_id'] for row in observations if row['units'] > 0} & ids
    return {'scope': 'all_filtered', 'stocked': sum(quantities[pk] > 0 for pk in known),
            'zero_stock': sum(quantities[pk] == 0 for pk in known), 'sold': len(sold),
            'unknown_stock': len(ids - known)}
