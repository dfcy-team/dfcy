import csv
import io
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from .warehouse_fee_import import fields_for, import_fees
from .warehouse_fee_models import WarehouseFeeImportBatch
from .warehouse_fee_services import CURRENCIES, PREFIX, create_fee, operate, representation, scope_configs, scoped


def filtered(user, params, action='view'):
    rows = scoped(user, action).select_related('store', 'warehouse')
    for field, choices in {'kind': ['order', 'other'], 'status': ['draft', 'registered', 'void'],
                           'match_status': ['matched', 'unmatched', 'ambiguous', 'not_applicable']}.items():
        value = params.get(field)
        if value:
            if value not in choices:
                raise ValidationError({field: '筛选值无效。'})
            rows = rows.filter(**{field: value})
    for field in ['country', 'bill_month', 'currency']:
        value = params.get(field)
        if value:
            if field == 'bill_month':
                serializers.RegexField(r'^\d{4}-(0[1-9]|1[0-2])$').run_validation(value)
            rows = rows.filter(**{field: value})
    for field in ['store_id', 'warehouse_id']:
        if params.get(field):
            rows = rows.filter(**{field: serializers.IntegerField(min_value=1).run_validation(params[field])})
    if params.get('order_number'):
        rows = rows.filter(external_order_id=params['order_number'])
    return rows


def options(user):
    configs = scope_configs(user, 'view')
    stores = list(StoreMaster.objects.filter(tenant=user.tenant).select_related('platform').order_by('code'))
    warehouses = list(WarehouseMaster.objects.filter(tenant=user.tenant).order_by('code'))
    sites = list(CountrySiteMaster.objects.filter(tenant=user.tenant).order_by('country_code'))
    def branch_country(cfg, country):
        return all(country in cfg[key] for key in ['regions', 'site_countries'] if key in cfg)
    def store_ok(store, cfg):
        return branch_country(cfg, store.country_code) and (
            'store_ids' not in cfg or str(store.pk) in {str(v) for v in cfg['store_ids']}) and (
            'platforms' not in cfg or store.platform.platform_type in cfg['platforms'])
    if configs is not None:
        stores = [store for store in stores if any(store_ok(store, cfg) for cfg in configs)]
        warehouses = [wh for wh in warehouses if any(branch_country(cfg, wh.country_code) and
            ('warehouse_ids' not in cfg or str(wh.pk) in {str(v) for v in cfg['warehouse_ids']}) and
            (not ({'store_ids', 'platforms'} & set(cfg)) or any(store.country_code == wh.country_code and store_ok(store, cfg) for store in stores)) for cfg in configs)]
        sites = [site for site in sites if any(wh.country_code == site.country_code for wh in warehouses)]
    currencies = [c for c in CURRENCIES if configs is None or any('currencies' not in cfg or c in cfg['currencies'] for cfg in configs)]
    return {'countries': [{'code': code, 'name': name} for code, name in dict((site.country_code, site.name) for site in sites).items()],
            'warehouses': [{'id': wh.pk, 'code': wh.code, 'name': wh.name, 'country': wh.country_code} for wh in warehouses],
            'stores': [{'id': store.pk, 'code': store.code, 'name': store.name, 'country': store.country_code} for store in stores],
            'currencies': currencies}


class WarehouseFeeView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = PREFIX + 'view'
    write_permission_code = PREFIX + 'create'
    operation = ''

    def get(self, request, pk=None):
        if self.operation == 'options':
            return success_response(options(request.user))
        if self.operation == 'template':
            kind = request.query_params.get('kind', 'order')
            fields_for(kind)
            if request.query_params.get('format') == 'simple':
                from .warehouse_fee_simple_import import template_bytes
                raw = template_bytes(kind)
            else:
                path = Path(__file__).with_name('templates') / f'warehouse_fee_{kind}.xlsx'
                raw = path.read_bytes()
            response = HttpResponse(raw, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="warehouse_fee_{kind}.xlsx"'
            return response
        if self.operation == 'imports':
            batches = WarehouseFeeImportBatch.objects.filter(tenant=request.user.tenant, imported_by=request.user).order_by('-pk')[:50]
            return success_response({'results': [{'id': b.pk, 'kind': b.kind, 'file_name': b.file_name,
                'created_at': b.created_at, 'results': b.results} for b in batches]})
        rows = filtered(request.user, request.query_params, 'export' if self.operation == 'export' else 'view')
        if pk:
            row = rows.filter(pk=pk).first()
            if not row:
                raise NotFound('费用不存在或不在授权范围。')
            return success_response(representation(row, audit=True))
        if self.operation == 'export':
            if rows.count() > 10000:
                raise ValidationError('导出最多10000条，请缩小月份或国家范围。')
            content = io.StringIO(newline=''); writer = csv.writer(content)
            writer.writerow(['登记ID', '费用类型', '国家', '仓库', '店铺', '平台订单号', '账单编号', '账单月份', '费用项目', '来源费用编号', '金额', '币种', '状态', '关联状态'])
            for row in rows.order_by('pk').iterator():
                values = [row.pk, row.kind, row.country, row.warehouse.code if row.warehouse_id else '待分配', row.store.code if row.store else '', row.external_order_id,
                          row.bill_number, row.bill_month, row.fee_item, row.reference, str(row.amount), row.currency, row.status, row.match_status]
                writer.writerow(["'" + x if isinstance(x, str) and x.lstrip().startswith(('=', '+', '-', '@')) else x for x in values])
            response = HttpResponse('\ufeff' + content.getvalue(), content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="warehouse_fees.csv"'
            return response
        page = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('page', 1))
        size = serializers.IntegerField(min_value=1, max_value=100).run_validation(request.query_params.get('page_size', 20))
        summaries = [{'currency': s['currency'], 'amount': str(s['amount']), 'count': s['count']} for s in
                     rows.filter(status='registered').values('currency').annotate(amount=Sum('amount'), count=Count('pk')).order_by('currency')]
        return success_response({'count': rows.count(), 'results': [representation(row) for row in rows.order_by('-pk')[(page-1)*size:page*size]],
                                 'registered_totals': summaries, 'status_counts': list(rows.values('status').annotate(count=Count('pk')))})

    def post(self, request, pk=None):
        if self.operation == 'import':
            if request.data.get('registration_mode') == 'cny_simple':
                from .warehouse_fee_simple_import import import_simple
                return success_response(import_simple(request.user, request.data.get('kind'), request.FILES.get('file'),
                    confirm=request.data.get('confirm') == 'true', expected_hash=request.data.get('sha256', ''),
                    valid_only=request.data.get('valid_only') == 'true'))
            return success_response(import_fees(request.user, request.data.get('kind'), request.FILES.get('file'),
                confirm=request.data.get('confirm') == 'true', expected_hash=request.data.get('sha256', ''), valid_only=request.data.get('valid_only') == 'true'))
        if self.operation == 'batch-register':
            targets = request.data.get('targets')
            if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
                raise ValidationError('请选择1至100条草稿。')
            if any(not isinstance(t, dict) or set(t) != {'id', 'version'} or type(t['id']) is not int for t in targets):
                raise ValidationError('登记ID及版本无效。')
            if len({t['id'] for t in targets}) != len(targets):
                raise ValidationError('不能重复选择同一费用。')
            with transaction.atomic():
                results = [representation(operate(request.user, t['id'], 'register', t['version'])) for t in sorted(targets, key=lambda t: t['id'])]
            return success_response({'results': results})
        if pk:
            unknown = set(request.data) - {'expected_version', 'changes', 'reason'}
            if unknown:
                raise ValidationError('操作包含未支持字段。')
            row = operate(request.user, pk, self.operation, request.data.get('expected_version'),
                          changes=request.data.get('changes'), reason=request.data.get('reason', ''))
            return success_response(representation(row))
        if request.data.get('registration_mode') == 'cny_simple':
            from .warehouse_fee_registration import prepare_registration
            data, source = prepare_registration(request.user, {k: v for k, v in request.data.items() if k != 'registration_mode'})
            row, created = create_fee(request.user, data, source=source)
        else:
            row, created = create_fee(request.user, request.data)
        return success_response(representation(row), status=201 if created else 200)


def fee_endpoint(operation='', *, read='view', write='create', methods=None):
    return type('WarehouseFeeEndpoint', (WarehouseFeeView,), {'__module__': __name__, 'operation': operation,
        'read_permission_code': PREFIX + read, 'write_permission_code': PREFIX + write,
        'http_method_names': methods or ['get', 'post', 'head', 'options']}).as_view()
