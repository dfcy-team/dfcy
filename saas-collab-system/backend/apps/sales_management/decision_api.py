"""Read-only API for the shared inventory/replenishment business view."""
from io import BytesIO

from django.db.models import Q
from django.http import FileResponse
from django.db import transaction
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
    decision_state = serializers.ChoiceField(choices=["all", "positive", "ready", "pending", "normal", "risk", "not_evaluated", "no_rules"], default="all")
    refresh = serializers.BooleanField(default=False)


class CountryDecisionAPI(InternalAPI):
    read_permission_code = domain.INVENTORY
    write_permission_code = operating.MANAGE


class CountryDecisions(CountryDecisionAPI):
    def get(self, request):
        query = DecisionQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        permission_cache = getattr(request, '_permission_resolution_cache', {})
        countries = list(domain.countries_for(request.user, permission_cache))
        country_options = [{'id': c.pk, 'name': c.name, 'country_code': c.country_code} for c in countries]
        result, count, can_write, summary, page_data = [], 0, False, None, {}
        if 'country_id' in values:
            country = domain.country_for(request.user, values['country_id'], permission_cache)
            rows = domain.skus_for(request.user, country, permission_cache).select_related('spu__category_node').order_by('sku_code', 'pk')
            if values['search'].strip():
                search = values['search'].strip()
                rows = rows.filter(Q(sku_code__icontains=search) | Q(legacy_sku_code__icontains=search) |
                                   Q(product_name__icontains=search))
            if values['decision_state'] == 'all' and 'decision_state' not in request.query_params:
                from apps.alerts.inventory_decisions import decision_page
                result, count, summary = decision_page(request.user, country, rows,
                    decision_state='all', window_days=values['window_days'],
                    target_days=values['target_days'], offset=values['offset'], limit=values['limit'])
            else:
                from apps.alerts.inventory_views import menu_page
                page_data = menu_page(request.user, country, decision_state=values['decision_state'],
                    window_days=values['window_days'], target_days=values['target_days'], search=values['search'],
                    offset=values['offset'], limit=values['limit'], permission_cache=permission_cache, refresh=values['refresh'])
                result, count, summary = page_data['results'], page_data['count'], page_data['summary']
            if check_user_permission(request.user, operating.MANAGE, cache=permission_cache):
                scopes = get_permission_data_scopes(request.user, operating.MANAGE, cache=permission_cache)
                can_write = any(s['scope_type'] in ['all', 'own'] or (
                    s['scope_type'] == 'custom' and country.pk in operating.country_ids(s)) for s in scopes)
        return Response({'data': {'countries': country_options, 'results': result, 'count': count, 'summary': summary,
            'parameters': {'target_days': values['target_days'], 'window_days': values['window_days'],
                           'as_of': business_date().isoformat()},
            'permissions': {'can_preview': can_write, 'can_create': can_write,
                            'can_evaluate': check_user_permission(request.user, 'alerts.evaluate', cache=permission_cache)}, 'notice': domain.NOTICE, **page_data}})


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
