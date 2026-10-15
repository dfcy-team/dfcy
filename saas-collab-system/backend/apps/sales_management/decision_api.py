"""Read-only API for the shared inventory/replenishment business view."""
from datetime import timedelta
from io import BytesIO

from django.db.models import Q
from django.http import FileResponse
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.commerce import country_decisions as domain
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.supply_chain.api import validated
from apps.supply_chain.dates import business_date
from apps.supply_chain.supplier_product_images import load_product_images
from apps.supply_chain.supplier_products import product_details
from apps.supply_chain.views import InternalAPI
from . import operating


class DecisionQuery(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(max_length=160, allow_blank=True, default='')
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    target_days = serializers.IntegerField(min_value=1, max_value=365, default=60)
    window_days = serializers.ChoiceField(choices=[7, 15, 30], default=30)


class CountryDecisionAPI(InternalAPI):
    read_permission_code = domain.INVENTORY
    write_permission_code = operating.MANAGE


class CountryDecisions(CountryDecisionAPI):
    def get(self, request):
        query = DecisionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        countries = list(domain.countries_for(request.user))
        country_options = [{'id': c.pk, 'name': c.name, 'country_code': c.country_code} for c in countries]
        result, count, can_write = [], 0, False
        if 'country_id' in values:
            country = domain.country_for(request.user, values['country_id'])
            rows = domain.skus_for(request.user, country).select_related('spu__category_node').order_by('sku_code', 'pk')
            if values['search'].strip():
                search = values['search'].strip()
                rows = rows.filter(Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search) |
                                   Q(product_name__icontains=search))
            count = rows.count()
            selected = list(rows[values['offset']:values['offset'] + values['limit']])
            result = domain.decision_rows(request.user, country, selected, target_days=values['target_days'],
                window_days=values['window_days'])
            if check_user_permission(request.user, operating.MANAGE):
                scopes = operating._require(request.user, operating.MANAGE)
                can_write = any(s['scope_type'] in ['all', 'own'] or (
                    s['scope_type'] == 'custom' and country.pk in operating.country_ids(s)) for s in scopes)
        return Response({'data': {'countries': country_options, 'results': result, 'count': count,
            'parameters': {'target_days': values['target_days'], 'window_days': values['window_days'],
                           'as_of': business_date().isoformat()},
            'permissions': {'can_preview': can_write, 'can_create': can_write,
                            'can_evaluate': check_user_permission(request.user, 'alerts.evaluate')}, 'notice': domain.NOTICE}})


class AlertEvaluationInput(serializers.Serializer):
    country_id = serializers.IntegerField(min_value=1)
    sku_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=100)
    window_days = serializers.ChoiceField(choices=[7, 15, 30], default=30)
    target_days = serializers.IntegerField(min_value=1, max_value=365, default=60)


class CountryDecisionAlerts(CountryDecisionAPI):
    write_permission_code = 'alerts.evaluate'

    @transaction.atomic
    def post(self, request):
        from apps.alerts.models import InventoryAlertRule
        from apps.alerts.services import evaluate_inventory_alert
        from apps.supply_chain.services import _tenant_lock
        _tenant_lock(request.user)
        values = validated(AlertEvaluationInput, request)
        country = domain.country_for(request.user, values['country_id'])
        ids = values['sku_ids']
        skus = list(domain.skus_for(request.user, country).filter(pk__in=ids).select_related('spu__category_node'))
        if len(ids) != len(set(ids)) or len(skus) != len(ids):
            raise serializers.ValidationError('商品不存在、重复或超出授权范围。')
        observations = domain.decision_rows(request.user, country, skus, target_days=values['target_days'],
            window_days=values['window_days'])
        rules = {}
        for rule in InventoryAlertRule.objects.filter(tenant_id=request.user.tenant_id, is_enabled=True,
                effective_at__lte=timezone.now()).order_by('rule_code', '-version', '-pk'):
            rules.setdefault(rule.rule_code, rule)
        by_id = {sku.pk: sku for sku in skus}
        created, updated, skipped = 0, 0, []
        warehouse_code = f'COUNTRY:{country.country_code.upper()}'
        for row in observations:
            sku = by_id[row['sku_id']]
            observed = next(w for w in row['sales_windows'] if w['days'] == values['window_days'])
            problems = list(row['issues'])
            if (not row['inventory_complete'] or not observed['coverage_complete'] or
                row['suggested_quantity'] is None):
                skipped.append({'sku_id': sku.pk, 'issues': problems})
                continue
            scopes = get_permission_data_scopes(request.user, 'alerts.evaluate')
            # Country totals cannot satisfy a grant restricted to one warehouse.
            allowed = request.user.is_superuser or any(s['scope_type'] == 'all' or (
                s['scope_type'] == 'custom' and set(s.get('config') or {}) == {'sku_ids'} and
                sku.pk in s['config']['sku_ids']) for s in scopes)
            if not allowed:
                skipped.append({'sku_id': sku.pk, 'issues': ['alert_target_not_authorized']})
                continue
            for rule in rules.values():
                alert, is_new = evaluate_inventory_alert(tenant=request.user.tenant, rule=rule, sku=sku,
                    warehouse_code=warehouse_code, available_stock=row['available_stock'],
                    in_transit_stock=row['pipeline']['effective_incoming'], average_daily_sales=row['daily_sales'],
                    source_summary={'mode': 'real_observation', 'contains_real_data': True,
                        'country_id': country.pk, 'country_code': country.country_code, 'window_days': values['window_days'],
                        'source_snapshot_ids': row['source_snapshot_ids'], 'source_run_ids': row['source_run_ids'],
                        'issues': problems, 'formula': '可用库存 + 按期有效到货，除以窗口日均销量'})
                created += int(bool(alert and is_new))
                updated += int(bool(alert and not is_new))
        return Response({'data': {'mode': 'real_observation', 'created': created, 'updated': updated,
            'skipped': skipped, 'rule_count': len(rules), 'notification_sent': False}})


class CountryDecisionImage(CountryDecisionAPI):
    def get(self, request, country_id, sku_id):
        country = domain.country_for(request.user, country_id)
        sku = domain.skus_for(request.user, country).filter(pk=sku_id).select_related('spu__category_node').first()
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
