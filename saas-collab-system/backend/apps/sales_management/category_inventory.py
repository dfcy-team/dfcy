from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.commerce import country_decisions as domain
from apps.commerce.models import SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductCategory
from .decision_api import CountryDecisionAPI
from .inventory_queries import latest_country_inventory
from .scopes import filter_inventory_queryset, filter_sales_queryset


class CategoryQuery(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1, required=False)
    category_id = serializers.IntegerField(min_value=0, required=False)
    spu_id = serializers.IntegerField(min_value=1, required=False)
    sku_id = serializers.IntegerField(min_value=1, required=False)
    level = serializers.ChoiceField(choices=['category', 'spu', 'sku', 'stores', 'warehouses'], default='category')
    days = serializers.ChoiceField(choices=[7, 15, 30], default=30)
    search = serializers.CharField(max_length=160, required=False, allow_blank=True, default='')
    offset = serializers.IntegerField(min_value=0, default=0)


def _load_stock_facts(actor, country, permissions):
    source = latest_country_inventory(domain._country_inventory_source(actor, country, timezone.now()))
    source = filter_inventory_queryset(actor, domain.INVENTORY, source, permission_cache=permissions)
    source = source.filter(warehouse__status='active', internal_sku_id__in=domain.skus_for(actor, country, permissions).values('pk'))
    rows = list(source.order_by().values(
        'internal_sku_id', 'warehouse_id', 'warehouse__name', 'available_qty',
        'provided_quantity_fields', 'source_run__status', 'source_run__failed_count'))
    aliases = Counter((row['internal_sku_id'], row['warehouse_id']) for row in rows)
    for row in rows:
        known = (aliases[row['internal_sku_id'], row['warehouse_id']] == 1
                 and 'available_qty' in (row['provided_quantity_fields'] or [])
                 and row['source_run__status'] == 'success' and not row['source_run__failed_count']
                 and row['available_qty'] is not None and row['available_qty'] >= 0)
        row['available_qty'] = row['available_qty'] if known else None
    return rows


def stock_facts(actor, country, permissions):
    key = f'country-stock-facts:v2:{actor.tenant_id}:{actor.pk}:{country.pk}:{domain.permission_signature(actor, permissions)}'
    return cache.get_or_set(key, lambda: _load_stock_facts(actor, country, permissions), 60)


def sales_facts(actor, country, days, permissions, sku_ids=None):
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
        rows = SalesOrderItem.objects.filter(
            sales_order__tenant_id=actor.tenant_id, sales_order__store_id__in=store_ids,
            sales_order__created_at_utc__gte=lower, sales_order__created_at_utc__lt=upper,
            sales_order__paid_at_utc__lt=upper,
            sales_order__normalized_status__in=['confirmed', 'fulfilled', 'completed'],
            sales_order__source_run__status='success', sales_order__source_run__failed_count=0,
            internal_sku_id__isnull=False)
        if sku_ids is None:
            fields = ('internal_sku_id',)
        else:
            rows = rows.filter(internal_sku_id__in=sku_ids)
            fields = ('sales_order__store_id', 'sales_order__store__name',
                      'sales_order__store__platform__platform_type', 'currency')
        result.extend(rows.order_by().values(*fields).annotate(units=Sum('quantity'), amount=Sum('line_total_amount')))
    return result


def totals(ids, stock, sales):
    inventory = [stock[pk] for pk in ids if pk in stock]
    units = [sales[pk] for pk in ids if pk in sales]
    return {'available': sum(inventory) if inventory else None, 'sales': sum(units) if units else None}


class CategoryInventory(CountryDecisionAPI):
    def get(self, request):
        query = CategoryQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        q = query.validated_data
        actor = request.user
        permissions = getattr(request, '_permission_resolution_cache', {})
        countries = list(domain.countries_for(actor, permissions).values('id', 'name', 'country_code'))
        if 'country_id' not in q:
            return Response({'data': {'countries': countries, 'results': [], 'count': 0}})
        country = domain.country_for(actor, q['country_id'], permissions)
        prefix = f'category-stock:v1:{actor.tenant_id}:{actor.pk}:{country.pk}:{domain.permission_signature(actor, permissions)}'
        snapshots = cache.get_or_set(prefix, lambda: stock_facts(actor, country, permissions), 60)
        stock = defaultdict(int)
        for row in snapshots:
            if row['available_qty'] is not None:
                stock[row['internal_sku_id']] += row['available_qty']
        catalog = domain.skus_for(actor, country, permissions).filter(
            pk__in={row['internal_sku_id'] for row in snapshots})
        if q['search']:
            from django.db.models import Q
            term = q['search']
            catalog = catalog.filter(Q(sku_code__icontains=term) | Q(legacy_sku_code__icontains=term)
                | Q(product_name__icontains=term) | Q(spu__product_name__icontains=term)
                | Q(specification__icontains=term))
        categories = {row['id']: row for row in ProductCategory.objects.filter(
            tenant_id=actor.tenant_id).values('id', 'parent_id', 'name')}
        category_id = q.get('category_id')
        if category_id and category_id not in categories:
            raise NotFound('类目不存在。')
        descendants = {category_id}
        for _ in range(3):
            descendants.update(pk for pk, node in categories.items() if node['parent_id'] in descendants and node['parent_id'])
        if category_id == 0:
            catalog = catalog.filter(spu__category_node__isnull=True)
        elif category_id:
            catalog = catalog.filter(spu__category_node_id__in=descendants)
        if 'spu_id' in q:
            catalog = catalog.filter(spu_id=q['spu_id'])
        if 'sku_id' in q:
            catalog = catalog.filter(pk=q['sku_id'])
        products = list(catalog.order_by('sku_code', 'pk').values(
            'id', 'sku_code', 'legacy_sku_code', 'specification', 'product_name',
            'spu_id', 'spu__spu_code', 'spu__product_name', 'spu__category_node_id'))
        ids = {row['id'] for row in products}
        level = q['level']
        summary = {}
        if level == 'warehouses':
            results = [{'name': row['warehouse__name'], 'available': row['available_qty']}
                       for row in snapshots if row['internal_sku_id'] in ids] if q.get('sku_id') else []
        elif level == 'stores':
            results = sales_facts(actor, country, q['days'], permissions, ids) if ids and (q.get('spu_id') or q.get('sku_id')) else []
            results.sort(key=lambda row: (-row['units'], row['sales_order__store_id'], row['currency']))
        else:
            observations = cache.get_or_set(f'{prefix}:sales:{q["days"]}',
                lambda: sales_facts(actor, country, q['days'], permissions), 120)
            # Timezone groups may contain the same SKU.
            sales = defaultdict(int)
            for row in observations:
                sales[row['internal_sku_id']] += row['units']
            summary = {**totals(ids, stock, sales), 'sku_count': len(ids),
                       'spu_count': len({row['spu_id'] for row in products})}
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
                if level == 'category':
                    name = categories.get(key, {}).get('name', '未分类')
                    has_children = any(row['spu__category_node_id'] != key for row in items) if key else False
                    values.update(has_children=has_children)
                elif level == 'spu':
                    name = first['spu__product_name']
                    values.update(code=first['spu__spu_code'])
                else:
                    name = first['product_name'] or first['spu__product_name']
                    values.update(code=first['sku_code'], legacy=first['legacy_sku_code'], specification=first['specification'])
                results.append({'id': key, 'name': name, 'sku_count': len(items),
                                'spu_count': len({row['spu_id'] for row in items}), **values})
            results.sort(key=lambda row: (row['id'] == 0, row['name'], row['id']))
        offset = q['offset']
        return Response({'data': {'countries': countries, 'summary': summary, 'count': len(results),
                                  'results': results[offset:offset + 20]}})


def operations_summary(actor, country, skus, days, permissions):
    key = f'operations-summary:v1:{actor.tenant_id}:{actor.pk}:{country.pk}:{domain.permission_signature(actor, permissions)}'
    snapshots = cache.get_or_set(key, lambda: stock_facts(actor, country, permissions), 60)
    observations = cache.get_or_set(key + f':sales:{days}', lambda: sales_facts(actor, country, days, permissions), 120)
    ids = set(skus.order_by().values_list('pk', flat=True))
    quantities = defaultdict(int)
    known, unknown = set(), set()
    for row in snapshots:
        pk = row['internal_sku_id']
        if pk not in ids:
            continue
        if row['available_qty'] is None:
            unknown.add(pk)
        else:
            known.add(pk)
            quantities[pk] += row['available_qty']
    known -= unknown
    sold = {row['internal_sku_id'] for row in observations if row['units'] > 0} & ids
    return {'scope': 'all_filtered', 'stocked': sum(quantities[pk] > 0 for pk in known),
            'zero_stock': sum(quantities[pk] == 0 for pk in known), 'sold': len(sold),
            'unknown_stock': len(ids - known)}
