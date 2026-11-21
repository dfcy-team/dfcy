"""Read-only API for the shared inventory/replenishment business view."""
from io import BytesIO
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.http import FileResponse
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.commerce import country_decisions as domain
from apps.products.models import ProductCategory
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.supply_chain.api import validated
from apps.supply_chain.dates import business_date
from apps.supply_chain.supplier_product_images import load_product_images
from apps.supply_chain.supplier_products import product_details
from apps.supply_chain.views import InternalAPI
from . import operating


class DecisionQuery(serializers.Serializer):
    abc_grade = serializers.ChoiceField(choices=["", "A", "B", "C", "new", "no_sales", "unavailable"], default="")
    country_id = serializers.IntegerField(min_value=1, required=False)
    category_id = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(max_length=160, allow_blank=True, default='')
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    target_days = serializers.IntegerField(min_value=1, max_value=365, default=60)
    window_days = serializers.ChoiceField(choices=[7, 15, 30], default=30)
    decision_state = serializers.ChoiceField(choices=["all", "positive", "ready", "pending", "normal", "risk", "not_evaluated", "no_rules"], default="all")
    refresh = serializers.BooleanField(default=False)
    mapped_only = serializers.BooleanField(default=False)
    group_by = serializers.ChoiceField(choices=['sku', 'spu'], default='sku')
    category_ids = serializers.CharField(max_length=2000, allow_blank=True, required=False, default='')

    def validate_category_ids(self, raw):
        if not raw.strip():
            return set()
        parts = [part.strip() for part in raw.split(',')]
        if len(parts) > 100 or any(not part.isascii() or not part.isdecimal() or len(part) > 19 for part in parts):
            raise serializers.ValidationError('类目参数无效或超过100项。')
        ids = {int(part) for part in parts}
        if any(pk <= 0 or pk > 2**63 - 1 for pk in ids):
            raise serializers.ValidationError('类目参数无效。')
        return ids

    def validate(self, attrs):
        if attrs['group_by'] == 'spu' and not attrs['mapped_only']:
            raise serializers.ValidationError('SPU 分组仅适用于库存经营。')
        if attrs['mapped_only'] and attrs['decision_state'] != 'all':
            raise serializers.ValidationError('已映射观察页不使用完整决策分类筛选，请使用 all。')
        if attrs['category_ids'] and (attrs['group_by'] != 'spu' or not attrs['mapped_only']):
            raise serializers.ValidationError('多类目筛选仅适用于 SPU 库存经营。')
        if 'category_id' in attrs and not attrs['mapped_only']:
            raise serializers.ValidationError('类目筛选仅适用于已映射库存工作台。')
        return attrs


def mapped_category_options(actor, rows):
    """Expose only categories represented by scoped stock and their ancestors."""
    catalog = {c['id']: c for c in ProductCategory.objects.filter(
        tenant_id=actor.tenant_id).values('id', 'name', 'parent_id', 'level')}
    visible = set()
    for category_id in rows.order_by().values_list('spu__category_node_id', flat=True).distinct():
        seen = set()
        while category_id in catalog and category_id not in seen:
            seen.add(category_id)
            visible.add(category_id)
            category_id = catalog[category_id]['parent_id']
    nodes = {pk: {'id': pk, 'name': catalog[pk]['name'], 'children': []} for pk in visible}
    roots = []
    for pk in sorted(visible):
        parent = catalog[pk]['parent_id']
        if parent in nodes and catalog[parent]['level'] < catalog[pk]['level']:
            nodes[parent]['children'].append(nodes[pk])
        else:
            roots.append(nodes[pk])
    return roots, catalog, visible


def category_descendants(category_id, catalog):
    selected = {category_id}
    while True:
        expanded = selected | {pk for pk, node in catalog.items() if node['parent_id'] in selected}
        if expanded == selected:
            return selected
        selected = expanded


class CountryDecisionAPI(InternalAPI):
    read_permission_code = domain.INVENTORY
    write_permission_code = operating.MANAGE


def _known_sum(values):
    values = list(values)
    if not values or any(value is None or isinstance(value, bool) for value in values):
        return None
    try:
        numbers = [Decimal(str(value)) for value in values]
        if any(not value.is_finite() for value in numbers):
            return None
        total = sum(numbers, Decimal(0))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return int(total) if total == total.to_integral_value() else float(total)


def _group_inventory_spus(rows, metadata, window_days):
    """Combine a bounded, already-computed SKU page into complete SPU groups."""
    grouped = {}
    for row in rows:
        sku_id = row.get('sku_id')
        spu_id = row.get('spu_id')
        meta = metadata.get(sku_id, {})
        spu_id = meta.get('spu_id', spu_id)
        key = spu_id or row.get('sku')
        if key not in grouped:
            parent = dict(row)
            parent.update({
                'sku_id': f'spu-{key}', 'spu_id': spu_id, 'sku': meta.get('spu_code') or '',
                'legacy_sku_code': meta.get('legacy_spu_code') or '', 'product_name': meta.get('product_name') or '',
                '__spu': True, 'variants': [], 'sku_count': 0,
            })
            grouped[key] = parent
        grouped[key]['variants'].append(row)
    output = []
    for parent in grouped.values():
        variants = parent['variants']
        parent['sku_count'] = len(variants)
        parent['spu_code'] = parent['sku']
        parent['legacy_spu_code'] = parent['legacy_sku_code']
        parent['available_stock'] = str(_known_sum(row.get('available_stock') for row in variants)) if _known_sum(row.get('available_stock') for row in variants) is not None else None
        parent['on_hand_stock'] = _known_sum(row.get('on_hand_stock') for row in variants)
        parent['mapped_sales_units'] = _known_sum(row.get('mapped_sales_units') for row in variants)
        parent['mapped_only'] = all(row.get('mapped_only') for row in variants)
        parent['inventory_complete'] = all(row.get('inventory_complete') is True for row in variants)
        parent['mapped_sales_complete'] = all(row.get('mapped_sales_complete') is True for row in variants)
        parent['stock_sales_reason'] = None
        warehouse_groups = {}
        for row in variants:
            for warehouse in row.get('warehouses') or []:
                warehouse_groups.setdefault(warehouse.get('id'), []).append(warehouse)
        parent['warehouses'] = []
        for warehouse_id, facts in warehouse_groups.items():
            item = dict(facts[0])
            for field in ('available_qty', 'last_synced_qty', 'on_hand_qty', 'reserved_qty'):
                if any(field in fact for fact in facts):
                    item[field] = _known_sum(fact.get(field) for fact in facts)
            parent['warehouses'].append(item)
        parent['sales_windows'] = []
        window_sizes = sorted({window.get('days') for row in variants for window in row.get('sales_windows', []) if window.get('days') is not None})
        for days in window_sizes:
            windows = [next((w for w in row.get('sales_windows', []) if w.get('days') == days), None) for row in variants]
            existing = [w for w in windows if w is not None]
            item = dict(existing[0])
            item['units'] = _known_sum(w.get('units') if w is not None else None for w in windows)
            item['coverage_complete'] = len(existing) == len(variants) and all(w.get('coverage_complete') for w in existing)
            parent['sales_windows'].append(item)
        statuses = {(row.get('operations') or {}).get('inventory_status') for row in variants}
        parent['operations'] = dict(parent.get('operations') or {})
        parent['operations']['variant_distribution'] = {str(status): sum((row.get('operations') or {}).get('inventory_status') == status for row in variants) for status in sorted(statuses, key=lambda item: str(item))}
        parent['operations']['inventory_status'] = (next(iter(statuses)) or 'unknown') if len(statuses) == 1 else 'unknown'
        sales_states = {(row.get('operations') or {}).get('sales_status') for row in variants}
        parent['operations']['sales_status'] = ((next(iter(sales_states)) or 'unknown') if len(sales_states) == 1
                                                else 'unknown' if sales_states.intersection({None, 'unknown'}) else 'observed_sales')
        known_sales = _known_sum(row.get('mapped_sales_units') for row in variants)
        stock = parent['available_stock']
        try:
            parent['operations']['observed_coverage_days'] = round(float(stock) / (float(known_sales) / window_days), 2) if known_sales is not None and float(known_sales) > 0 and stock is not None else None
        except (TypeError, ValueError, ZeroDivisionError):
            parent['operations']['observed_coverage_days'] = None
        if not all((row.get('pipeline') or {}).get('authorized') is True for row in variants):
            parent['pipeline'] = {'authorized': False}
        else:
            pipeline_keys = {key for row in variants for key in (row.get('pipeline') or {}) if key not in {'authorized'}}
            parent['pipeline'] = {'authorized': True}
            for key in pipeline_keys:
                values = [(row.get('pipeline') or {}).get(key) for row in variants]
                if all(value is None or isinstance(value, (int, float, str, Decimal)) and not isinstance(value, bool) for value in values):
                    parent['pipeline'][key] = _known_sum(values)

        pictured = [row for row in variants if row.get('image_preview_url') and (row.get('mapped_sales_units') or 0) > 0]
        parent['image_preview_url'] = (pictured or [row for row in variants if row.get('image_preview_url')] or [{}])[0].get('image_preview_url') or ''
        output.append(parent)
    return output


class CountryDecisions(CountryDecisionAPI):
    def get(self, request):
        query = DecisionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        permission_cache = getattr(request, '_permission_resolution_cache', {})
        countries = list(domain.countries_for(request.user, permission_cache, include_best=True))
        country_options = [{'id': c.pk, 'name': c.name, 'country_code': c.country_code} for c in countries]
        result, count, can_write, summary, page_data = [], 0, False, None, {}
        category_options = []
        if values['group_by'] == 'spu':
            catalog = {c['id']: c for c in ProductCategory.objects.filter(tenant_id=request.user.tenant_id).values('id', 'name', 'parent_id', 'level')}
            nodes = {pk: {'id': pk, 'name': row['name'], 'children': []} for pk, row in catalog.items()}
            for pk, row in catalog.items():
                parent = row['parent_id']
                if parent in nodes and catalog[parent]['level'] < row['level']:
                    nodes[parent]['children'].append(nodes[pk])
                else:
                    category_options.append(nodes[pk])
        if 'country_id' in values:
            country = next((item for item in countries if item.pk == values['country_id']), None)
            if country is None:
                raise NotFound('国家不存在或不在库存数据授权范围内。')
            rows = domain.skus_for(request.user, country, permission_cache, include_best=True).select_related('spu__category_node').order_by('sku_code', 'pk')
            if values['mapped_only']:
                inventory_context = domain.inventory_context_for(request.user, country, include_best=True, permission_cache=permission_cache)
                rows = rows.filter(pk__in=inventory_context['by_sku'])
                mapped_options, catalog, visible = mapped_category_options(request.user, rows)
                if values['group_by'] != 'spu':
                    category_options = mapped_options
                requested_categories = values['category_ids']
                if requested_categories:
                    if not requested_categories <= set(catalog):
                        raise serializers.ValidationError({'category_ids': '类目不存在。'})
                    selected_category_ids = set()
                    for category_id in requested_categories:
                        selected_category_ids.update(category_descendants(category_id, catalog))
                    rows = rows.filter(spu__category_node_id__in=selected_category_ids)
                if 'category_id' in values:
                    if values['category_id'] not in visible:
                        raise serializers.ValidationError('类目不在当前国家已映射商品范围内，请重新选择。')
                    rows = rows.filter(spu__category_node_id__in=category_descendants(values['category_id'], catalog))
            base_rows = rows
            from .abc_access import filter_skus
            grouped = values['mapped_only'] and values['group_by'] == 'spu'
            rows = filter_skus(request.user, country, rows, values['abc_grade'], grouped=grouped)
            if values['search'].strip():
                search = values['search'].strip()
                rows = rows.filter(Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search) |
                                   Q(product_name__icontains=search) | Q(spu__product_name__icontains=search) |
                                   Q(spu__spu_code__icontains=search) | Q(spu__legacy_spu_code__icontains=search) |
                                   Q(specification__icontains=search) | Q(size__icontains=search) | Q(material__icontains=search))
            summary_rows = rows
            if values['mapped_only'] or (values['decision_state'] == 'all' and 'decision_state' not in request.query_params):
                from apps.alerts.inventory_decisions import decision_page
                if values['mapped_only']:
                    if grouped:
                        matching_spus = rows.order_by().values('spu_id').distinct()
                        page_spus = list(rows.order_by('spu_id').values_list('spu_id', flat=True).distinct()[values['offset']:values['offset'] + values['limit']])
                        # Once a scoped SPU matches, fetch every scoped sibling,
                        # not just the individual SKU that matched the search.
                        summary_rows = base_rows.filter(spu_id__in=matching_spus)
                        page_rows = base_rows.filter(spu_id__in=page_spus).order_by('spu_id', 'sku_code', 'pk')
                        count = matching_spus.count()
                    else:
                        ids = list(rows.values_list('pk', flat=True)[values['offset']:values['offset'] + values['limit']])
                        page_rows = rows.filter(pk__in=ids)
                        count = rows.count()
                    ids = list(page_rows.values_list('pk', flat=True))
                    # No old cached page/context is reused across run or scope changes.
                    result, _, _ = decision_page(request.user, country, page_rows, decision_state='all',
                        window_days=values['window_days'], target_days=values['target_days'],
                        offset=0, limit=len(ids), mapped_only=True,
                        inventory_context=inventory_context, include_best=True)
                    if grouped:
                        metadata = {item['pk']: item for item in page_rows.values('pk', 'spu_id', 'spu__spu_code', 'spu__legacy_spu_code', 'spu__product_name')}
                        spu_metadata = {pk: {'spu_id': item['spu_id'], 'spu_code': item['spu__spu_code'], 'legacy_spu_code': item['spu__legacy_spu_code'], 'product_name': item['spu__product_name']} for pk, item in metadata.items()}
                else:
                    result, count, summary = decision_page(request.user, country, rows,
                        decision_state='all', window_days=values['window_days'], target_days=values['target_days'],
                        offset=values['offset'], limit=values['limit'], include_best=True)
            else:
                from apps.alerts.inventory_views import menu_page
                page_data = menu_page(request.user, country, decision_state=values['decision_state'],
                    window_days=values['window_days'], target_days=values['target_days'], search=values['search'],
                    offset=values['offset'], limit=values['limit'], permission_cache=permission_cache, refresh=values['refresh'])
                result, count, summary = page_data['results'], page_data['count'], page_data['summary']
            if values['mapped_only']:
                from .category_inventory import operations_summary
                snapshots = domain.mapped_inventory_facts(inventory_context, summary_rows.order_by().select_related(None).only('id', 'spu_id'))
                summary = operations_summary(request.user, country, summary_rows, values['window_days'], permission_cache, snapshots=snapshots)
            from apps.commerce.inventory_listing import linked_sku_ids, apply_listing_observation
            listing_ids = linked_sku_ids(request.user.tenant_id, country.country_code, [item['sku_id'] for item in result])
            for item in result:
                apply_listing_observation(item, item['sku_id'] in listing_ids,
                                          window_days=values['window_days'], target_days=values['target_days'])
            if grouped:
                result = _group_inventory_spus(result, spu_metadata, values['window_days'])
                for parent in result:
                    states = {variant.get('platform_mapping_status') for variant in parent['variants']}
                    if len(states) == 1 and states <= {'linked', 'unlinked'}:
                        apply_listing_observation(parent, 'linked' in states,
                            window_days=values['window_days'], target_days=values['target_days'])
                    else:
                        parent.pop('stock_sales_status', None)
                        parent.pop('stock_sales_reason', None)
                        parent['platform_mapping_status'] = 'mixed'
                        parent['platform_mapping_label'] = '款式关联状态不一致，请查看明细'
                        parent['operations']['action'] = '查看款式明细'
            if check_user_permission(request.user, operating.MANAGE, cache=permission_cache):
                scopes = get_permission_data_scopes(request.user, operating.MANAGE, cache=permission_cache)
                can_write = any(s['scope_type'] in ['all', 'own'] or (s['scope_type'] == 'custom' and country.pk in operating.country_ids(s)) for s in scopes)
        abc_meta = {}
        if 'country_id' in values:
            from .abc_access import decorate_rows
            abc_meta = decorate_rows(request.user, country, result)
        return Response({'data': {'abc_meta': abc_meta, 'countries': country_options, 'categories': category_options,
            'results': result, 'count': count, 'summary': summary,
            'parameters': {'target_days': values['target_days'], 'window_days': values['window_days'],
                           'as_of': business_date().isoformat(), 'mapped_only': values['mapped_only'],
                           'group_by': values['group_by'], 'include_virtual': False},
            'permissions': {'can_preview': can_write, 'can_create': can_write,
                            'can_evaluate': check_user_permission(request.user, 'alerts.evaluate', cache=permission_cache)},
            'notice': domain.NOTICE, **page_data}})


class AlertEvaluationInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    sku_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100)
    window_days = serializers.ChoiceField(choices=[7, 15, 30], default=30)
    target_days = serializers.IntegerField(min_value=1, max_value=365, default=60)


class CountryDecisionAlerts(CountryDecisionAPI):
    write_permission_code = 'alerts.evaluate'

    @transaction.atomic
    def post(self, request):
        from apps.alerts.inventory_decisions import evaluate_country
        values = validated(AlertEvaluationInput, request)
        country = domain.country_for(request.user, values['country_id'])
        ids = values['sku_ids']
        skus = list(domain.skus_for(request.user, country).filter(pk__in=ids).select_related('spu__category_node'))
        if len(ids) != len(set(ids)) or len(skus) != len(ids):
            raise serializers.ValidationError('商品不存在、重复或超出授权范围。')
        return Response({'data': evaluate_country(request.user, country, skus,
            window_days=values['window_days'], target_days=values['target_days'])})


class CountryDecisionImage(CountryDecisionAPI):
    def get(self, request, country_id, sku_id):
        country = domain.country_for(request.user, country_id, include_best=True)
        sku = domain.skus_for(request.user, country, include_best=True).filter(pk=sku_id).select_related('spu__category_node').first()
        if not sku:
            raise NotFound('商品不在经营数据授权范围内。')
        value = load_product_images({'lines': [{'sku_id': sku.pk, 'product_details': product_details(sku)}]},
                                   request.user.tenant_id).get(sku.pk, {})
        if not value.get('body'):
            raise NotFound('商品图片尚未维护或暂不可用。')
        response = FileResponse(BytesIO(value['body']), content_type='image/jpeg')
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
