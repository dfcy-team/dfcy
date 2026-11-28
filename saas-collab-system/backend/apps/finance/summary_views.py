import gzip
import hashlib
import json
import re
from collections import OrderedDict
from threading import Lock
from concurrent.futures import Future
from pathlib import Path

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response, error_response
from apps.permissions.api_permissions import IsFinanceViewer
from .summary_scopes import request_access
from .summary_service import dataset_for, metadata, save_state, engine, document_path, unpack_values


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_bootstrap(request):
    from .summary_models import FinanceSummaryDataset
    if request.query_params.get('direct') == '1':
        from apps.masterdata.models import StoreMaster
        from .summary_scopes import store_ids, signature, full_reader
        from .summary_service import require_access
        require_access(request.user)
        ids = store_ids(request.user)
        return success_response({'direct_query': True, 'dataset': None, 'revision': 0,
            'tenant_id': request.user.tenant_id, 'access_signature': signature(request.user, ids),
            'can_edit': False, 'can_view_settings': full_reader(request.user) and FinanceSummaryDataset.objects.filter(tenant=request.user.tenant, active=True).exists(),
            'scope_stores': list(StoreMaster.objects.filter(tenant=request.user.tenant, pk__in=ids)
                .order_by('code').values('id', 'code', 'country_code', 'currency', 'platform__platform_type'))})
    if not FinanceSummaryDataset.objects.filter(tenant=request.user.tenant, active=True).exists():
        from .summary_initialization import initialization_status
        return success_response(initialization_status(request.user))
    dataset = dataset_for(request.user)
    data = metadata(dataset, request.user, include_values=request.query_params.get('native') != '1',
                    lightweight=request.query_params.get('status') == '1' and bool(dataset.metadata.get('database_scope')))
    if not data.get('lightweight'):
        data['document_version'] = hashlib.sha256(repr(presentation_stamp()).encode()).hexdigest()[:16]
    response = success_response(data)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['POST'])
@permission_classes([IsFinanceViewer])
def summary_initialize(request):
    from .summary_initialization import request_initialization
    from .summary_jobs import job_data
    if set(request.data) != {'scope'}:
        raise ValidationError('请仅提供本次候选试算的店铺和日期范围。')
    row = request_initialization(request.user, request.data['scope'])
    data = job_data(row, request.user)
    return success_response(data, status=202 if data['pending'] else 200)


@api_view(['POST'])
@permission_classes([IsFinanceViewer])
def summary_publish(request, pk):
    from .summary_initialization import publish_candidate
    if request.data.get('confirm') is not True:
        raise ValidationError('请核对候选试算后明确确认发布。')
    dataset = publish_candidate(request.user, pk)
    return success_response(metadata(dataset, request.user, include_values=False, checkpoint=False))


@api_view(['POST'])
@permission_classes([IsFinanceViewer])
def summary_rebuild(request, pk):
    from .summary_service import require_access
    dataset = dataset_for(request.user, pk)
    require_access(request.user, write=True)
    data = serializers.IntegerField(min_value=0).run_validation(request.data.get('revision'))
    if data != dataset.accounting_state.revision:
        return error_response('FINANCE_REVISION_CONFLICT', '来源批次或设置已更新，请刷新后重新汇总。', status=409)
    if not dataset.metadata.get('database_scope'):
        raise ValidationError('尚未完成数据库来源迁移，未创建重新汇总任务。')
    payload = {'revision': data}
    if 'scope' in request.data:
        from .summary_maintenance import validate_scope
        payload['scope'] = validate_scope(request.user, request.data['scope'], dataset.metadata['database_scope'])
    return calculation_response(dataset, request.user, payload, kind='rebuild')


def calculation_response(dataset, user, payload, *, kind='query'):
    from .summary_jobs import request_calculation, job_data
    from .summary_scopes import scoped_payload
    if kind=='query': payload=scoped_payload(user,payload)
    data = job_data(request_calculation(dataset, user, payload, kind=kind), user)
    response = success_response(data['result'] if data.get('result') is not None else data,
                                status=202 if data['pending'] else 200)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_job(request, pk):
    from django.shortcuts import get_object_or_404
    from .summary_models import FinanceSummaryCalculation
    from .summary_jobs import job_data
    from .summary_service import require_access
    require_access(request.user)
    row = get_object_or_404(FinanceSummaryCalculation, pk=pk, tenant=request.user.tenant)
    response = success_response(job_data(row, request.user))
    response['Cache-Control'] = 'no-store'
    return response


def browser_document(html):
    # Use a parent-mediated API bridge in an opaque-origin sandbox. The frame
    # receives neither authorization tokens nor browser storage access.
    from .summary_browser_shell import with_browser_shell
    html = with_browser_shell(html)
    from .summary_database_document import compact_browser_inputs
    html = compact_browser_inputs(html)
    from .summary_composition import adapt_document
    html = adapt_document(html)
    bridge = Path(__file__).with_name('summary_bridge.js').read_text(encoding='utf-8')
    runtime = Path(__file__).with_name('summary_runtime.js').read_text(encoding='utf-8')
    tools = Path(__file__).with_name('summary_tools.js').read_text(encoding='utf-8')
    participation = Path(__file__).with_name('summary_participation.js').read_text(encoding='utf-8')
    accounting_rules = json.loads(Path(__file__).with_name('summary_accounting_rules.json').read_text(encoding='utf-8'))
    def adapt(match):
        attrs, source = match.groups()
        if 'application/json' in attrs:
            return match.group(0)
        if 'id="html2-shopee-recharge"' in attrs:
            source = source.replace("const screen={shop:'SP6TH',month:'2026-09',page:1};",
                "const screen={shop:data.shops[0]?.code||'',month:data.transactions[0]?.date?.slice(0,7)||SNAPSHOT.database?.facts?.[0]?.date?.slice(0,7)||'',page:1};")
            source = source.replace('function draw(){const shop=', 'function draw(){if(!shops.has(screen.shop))return;const shop=')
        for rule in accounting_rules:
            if 'id="' + rule['module'] + '"' in attrs:
                source = re.sub(rule['find'], lambda _: rule['replace'], source, count=1) if rule.get('regex') else source.replace(rule['find'], rule['replace'])
        if 'id="html2-tab-filters"' in attrs:
            source = source.replace('globalThis.HTML2_TAB_FILTERS={', 'globalThis.HTML2_TAB_FILTERS={memory:()=>JSON.parse(JSON.stringify(saved)),restoreMemory:value=>Object.assign(saved,value||{}),')
        # Modules install their render wrappers first; draw once after setup.
        source = source.replace('renderLedger();', 'globalThis.SAAS_RENDER();')
        if 'id="sku-summary-ui"' in attrs:
            source = source.replace('globalThis.SKU_SUMMARY={members:', 'members=SAAS_MEMO(members);query=SAAS_MEMO(query);globalThis.SKU_SUMMARY={members:')
        if 'id="html2-product-links"' in attrs:
            source = source.replace('globalThis.HTML2_PRODUCT_LINKS={group,query,identity}', 'query=SAAS_MEMO(query);globalThis.HTML2_PRODUCT_LINKS={group,query,identity}')
        if 'id="html2-advertising-columns"' in attrs:
            source = source.replace('const api={allocate,schedules,calculate,profit,', 'calculate=SAAS_MEMO(calculate);const api={allocate,schedules,calculate,profit,')
        if 'id="html2-store-hierarchy"' in attrs:
            source = source.replace('const api={stores,controls,sku,', 'stores=SAAS_MEMO(stores);controls=SAAS_MEMO(controls);orderAllocation=SAAS_MEMO(orderAllocation);sku=SAAS_MEMO(sku);const api={stores,controls,sku,')
        if 'id="html2-fee-rates"' in attrs:
            source = source.replace("const target=data.fees[kind].amount,key=", "const traced=globalThis.SAAS_FEE_PARTS?.(data,kind);if(traced)return traced;const target=data.fees[kind].amount,key=")
            source = source.replace('缺少可核对的子项时保留未细分费用', 'SKU与商品链接子项按本行已分摊金额及对应原订单／店铺原始子项净额构成拆分，保留冲销方向；缺少可核对的子项时保留待细分费用')
        return '<script'+attrs+'>'+re.sub(r'\blocalStorage\b', 'globalThis.SAAS_STORAGE', source)+'</script>'
    html = re.sub(r'<script([^>]*)>([\s\S]*?)</script>', adapt, html)
    html = html.replace('<head>', '<head><script>'+runtime+'</script><script>'+tools+'</script><script>'+bridge+'</script><script>'+participation+'</script>', 1)
    html = html.replace('仅保存在当前浏览器，不写入SaaS', '保存到本地SaaS，保留操作记录')
    html = html.replace('仅保存在当前浏览器，不写SaaS', '保存到本地SaaS，保留操作记录')
    html = html.replace('只保存在当前浏览器，不写入SaaS', '保存到本地SaaS，保留操作记录')
    html = html.replace('仅当前浏览器保存，不写入SaaS', '保存到本地SaaS，保留操作记录')
    html = html.replace('仅保存在当前浏览器', '保存到本地SaaS')
    html = html.replace('只保存在当前浏览器', '保存到本地SaaS')
    html = html.replace('仅当前浏览器生效', '已在本地SaaS生效')
    html = html.replace('将替换当前浏览器设置', '将替换本地SaaS共享设置')
    html = html.replace('含本浏览器流水费用修改／新增', '含本地SaaS流水费用修改／新增')
    html = html.replace('临时 HTML · 未替换 SaaS 页面', '本地SaaS · 已验收财务批次')
    html = html.replace('多平台统一汇总 · 当地币种 · 仅临时预览', '多平台统一汇总 · 当地币种')
    html = html.replace('</head>', '''<style>
main{max-width:none;margin:0;padding:8px 0 16px}
main>header,main>nav.tabs{display:none}
html,body{background:#f5f7fb;height:auto;min-height:0;overflow-y:hidden}
main>.notice{margin:0 0 8px;padding:8px 12px}
main>.mapping{margin:8px 0}
#filters{padding:8px 0}
.html2-clean #ledger-table{max-height:clamp(280px,calc(var(--host-height,956px) - 430px),600px)!important}
.band-table .column-bands .frozen-band{clip-path:none!important}
main>.notice{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 16px}
main>.notice .scope-details{margin-top:0}
main>.notice .scope-details[open]{flex-basis:100%}
.html2-clean #filters{padding:4px 0 8px!important}
#filters .period{display:none}
#panel-ledger>.bar{margin:8px 0}
#expense-caption:empty{display:none}
#saas-quality{margin:8px 0;color:#795110;font-size:12px}
#saas-quality>summary{cursor:pointer}
#saas-quality .quality-strip{margin:8px 0}
dialog{top:var(--dialog-top,0px);bottom:auto;height:var(--dialog-height,calc(var(--host-height,956px) - 180px));max-height:var(--dialog-height,calc(var(--host-height,956px) - 180px))}
@media(max-width:1400px){
 .summary-table td{padding:8px 12px}
 .band-table .column-bands th{height:28px;padding:3px 12px}
 .band-table thead tr:last-child th{top:28px;padding:8px 12px}
}
</style></head>''')
    return html


def presentation_stamp():
    return tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in
                 [Path(__file__), Path(__file__).with_name('summary_browser_shell.py'), Path(__file__).with_name('templates') / 'settings-shell-v1.html', Path(__file__).with_name('templates') / 'settings-shell-v1.json', Path(__file__).with_name('templates') / 'settings-layout-v1.js', Path(__file__).with_name('summary_participation.js'), Path(__file__).with_name('summary_accounting_rules.json'), Path(__file__).with_name('summary_database_document.py'), Path(__file__).with_name('summary_bridge.js'), Path(__file__).with_name('summary_runtime.js'), Path(__file__).with_name('summary_tools.js'), Path(__file__).with_name('summary_composition.py'), Path(__file__).with_name('summary_composition.js')])


_document_cache = OrderedDict()
_document_cache_bytes = 0
_document_cache_limit = 32 * 1024 * 1024
_document_cache_lock = Lock()
_document_builds = {}


def prepared_document(path, source_hash, source_stamp, presentation_version, tools_only=False, tools_store=None):
    global _document_cache_bytes
    key = (path, source_hash, source_stamp, presentation_version, tools_only, tools_store)
    with _document_cache_lock:
        if key in _document_cache:
            _document_cache.move_to_end(key)
            return _document_cache[key]
        pending = _document_builds.get(key)
        owner = pending is None
        if owner:
            pending = _document_builds[key] = Future()
    if not owner:
        return pending.result()
    try:
        from .summary_documents import load_fragment, save_fragment, document_generation_lock
        body = load_fragment(key)
        if body is None:
            with document_generation_lock(path):
                body = load_fragment(key)
                if body is None:
                    body = build_prepared_document(*key)
                    save_fragment(key,body)
        if len(body) <= _document_cache_limit:
            with _document_cache_lock:
                while _document_cache and _document_cache_bytes + len(body) > _document_cache_limit:
                    _document_cache_bytes -= len(_document_cache.popitem(last=False)[1])
                _document_cache[key] = body
                _document_cache_bytes += len(body)
        pending.set_result(body)
        return body
    except BaseException as error:
        pending.set_exception(error)
        raise
    finally:
        with _document_cache_lock:
            _document_builds.pop(key, None)



def build_prepared_document(path, source_hash, source_stamp, presentation_version, tools_only=False, tools_store=None):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as file:
        original = file.read()
    if hashlib.sha256(original.encode('utf-8')).hexdigest() != source_hash:
        raise ValidationError('财务批次来源校验失败，请恢复原始批次。')
    snapshot = None
    if tools_only:
        from .summary_database_document import prepare_tools_document
        prepared = prepare_tools_document(original, tools_store)
        if prepared is not None:
            original, snapshot = prepared
        else:
            from .summary_database_document import compact_tools_inputs
            original = compact_tools_inputs(original)
    document = browser_document(original)
    if tools_only:
        from .summary_database_document import pack_tools_document
        document = pack_tools_document(document, snapshot)
    return gzip.compress(document.encode('utf-8'), compresslevel=1)


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_document(request, pk):
    from django.http import HttpResponse
    dataset = dataset_for(request.user, pk)
    from .summary_scopes import full_reader
    if not full_reader(request.user):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('此入口包含完整批次数据，请使用授权范围内的汇总查询。')
    path = document_path(dataset)
    stamp = path.stat()
    tools_only = request.query_params.get('tools') == '1'
    tools_store = None
    if tools_only and dataset.metadata.get('database_scope'):
        ids = dataset.metadata.get('store_ids', [])
        try:
            tools_store = int(request.query_params.get('store') or ids[0])
        except (ValueError, TypeError, IndexError):
            raise ValidationError('请选择已纳入批次的店铺。') from None
        if tools_store not in ids:
            raise ValidationError('店铺不在当前批次范围内。')
    body = prepared_document(str(path), dataset.source_hash, (stamp.st_mtime_ns, stamp.st_size), presentation_stamp(), tools_only, tools_store)
    response = HttpResponse(body, content_type='text/html; charset=utf-8')
    response['Content-Encoding'] = 'gzip'
    response['Cache-Control'] = 'no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


class SaveInput(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    key = serializers.CharField(max_length=100)
    value = serializers.CharField(max_length=2_000_000, trim_whitespace=False)
    reason = serializers.CharField(max_length=1000)


@api_view(['POST'])
@permission_classes([IsFinanceViewer])
def summary_save(request, pk):
    dataset = dataset_for(request.user, pk)
    data = SaveInput(data=request.data)
    data.is_valid(raise_exception=True)
    saved = save_state(dataset, request.user, **data.validated_data)
    if saved is None:
        return error_response('FINANCE_REVISION_CONFLICT', '其他操作已更新此批次，请刷新后重新修改。', status=409)
    return success_response(saved, '已保存到本地SaaS。')


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_report(request, pk):
    dataset = dataset_for(request.user, pk)
    from .summary_scopes import full_reader
    if not full_reader(request.user):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied('此入口包含完整批次数据，请使用授权范围内的汇总查询。')
    view = request.query_params.get('view', 'store')
    mode = request.query_params.get('mode', 'operations')
    if view not in ['country', 'store', 'order', 'sku', 'product_link', 'detail'] or mode not in ['operations', 'finance']:
        raise ValidationError('汇总级别或口径无效。')
    filters = {key: request.query_params[key] for key in ['month','country','platform','store','currency','order','sku'] if request.query_params.get(key)}
    return success_response({'view': view, 'mode': mode, 'amount_scale': 6, 'revision': dataset.accounting_state.revision,
        'items': engine(dataset, {'action': 'report', 'state': unpack_values(dataset.accounting_state.values),
                                 'view': view, 'mode': mode, 'filters': filters})})


class TableInput(serializers.Serializer):
    view = serializers.ChoiceField(choices=['country', 'store', 'order', 'sku', 'product_link', 'detail'], default='store')
    mode = serializers.ChoiceField(choices=['operations', 'finance'], default='operations')
    scope = serializers.ChoiceField(choices=['store', 'product'], default='store')
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    row_key = serializers.CharField(max_length=2000, required=False)
    kind = serializers.CharField(max_length=100, required=False)
    source_key = serializers.CharField(max_length=2000, required=False)
    cost_page = serializers.IntegerField(min_value=1, required=False)
    flow_page = serializers.IntegerField(min_value=1, required=False)


def table_input(request):
    data = TableInput(data=request.query_params)
    data.is_valid(raise_exception=True)
    filters = {}
    for key in ['month', 'period_type', 'period', 'attribution', 'country', 'platform', 'store', 'currency', 'order', 'sku', 'product', 'from', 'to', 'kind', 'keyword', 'status', 'editable']:
        value = request.query_params.get('filter_' + key, '')
        if len(value) > 300:
            raise ValidationError('筛选内容过长。')
        if value:
            filters[key] = value
    from datetime import date
    if filters.get('attribution', 'assigned') not in ('assigned', 'pending'):
        raise ValidationError('费用归属范围无效。')
    if filters.get('attribution') == 'pending' and data.validated_data.get('view') != 'detail':
        raise ValidationError('待归属金额请在独立明细区核对，不生成虚拟店铺或利润。')
    period_type = filters.get('period_type', 'month')
    if period_type not in ('month', 'week', 'half_month'):
        raise ValidationError('统计维度无效。')
    if period_type != 'month':
        month = filters.get('month', '')
        try:
            if not re.fullmatch(r'\d{4}-\d{2}', month):
                raise ValueError()
            date.fromisoformat(month + '-01')
            period = filters.get('period', '')
            if period != 'undated':
                start = date.fromisoformat(period)
                if start.isoformat() != period or (period_type == 'week' and start.weekday() != 0) or (period_type == 'half_month' and start.day not in (1, 16)):
                    raise ValueError()
        except ValueError:
            raise ValidationError('请选择有效账期及周／半月区间，或待归期。')
    elif filters.get('period'):
        raise ValidationError('月度汇总不接受周／半月区间。')
    return {**data.validated_data, 'filters': filters}


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_table(request, pk):
    dataset = dataset_for(request.user, pk)
    return calculation_response(dataset, request.user, {'action': 'table', **table_input(request)})


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_table_detail(request, pk):
    dataset = dataset_for(request.user, pk)
    payload = table_input(request)
    if not payload.get('row_key') or not payload.get('kind'):
        raise ValidationError('请选择金额或费率。')
    return calculation_response(dataset, request.user, {'action': 'table_detail', **payload})


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_direct_table(request):
    from .summary_read_query import request_query
    from .summary_jobs import job_data
    context = request.query_params.get('query_context')
    if context is not None:
        context = serializers.IntegerField(min_value=1).run_validation(context)
    row = request_query(request.user, {'action': 'table', **table_input(request)}, context=context,
                        refresh=request.query_params.get('refresh') == '1')
    data = job_data(row, request.user)
    response = success_response(data['result'] if data.get('result') is not None else data,
                                status=202 if data['pending'] else 200)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_direct_detail(request):
    from django.shortcuts import get_object_or_404
    from .summary_models import FinanceSummaryCalculation
    from .summary_jobs import job_data, current_dataset, request_calculation, logical_payload
    from .summary_service import require_access
    require_access(request.user)
    context = serializers.IntegerField(min_value=1).run_validation(request.query_params.get('query_context'))
    parent = get_object_or_404(FinanceSummaryCalculation, pk=context, tenant=request.user.tenant,
                             kind='query', status='ready')
    parent_data = job_data(parent, request.user)
    dataset = current_dataset(parent)
    if not dataset or '_database_query' not in parent.request:
        raise ValidationError('查询来源或权限已变化，请重新查询汇总。')
    detail = TableInput(data=request.query_params)
    detail.is_valid(raise_exception=True)
    if not detail.validated_data.get('row_key') or not detail.validated_data.get('kind'):
        raise ValidationError('请选择金额或费率。')
    values = detail.validated_data
    if not values.get('source_key') and values.get('cost_page', 1) == 1 and values.get('flow_page', 1) == 1 and request.query_params.get('include_records') != '1':
        row = next((row for row in (parent_data.get('result') or {}).get('rows', [])
                    if row.get('key') == values['row_key']), {})
        kind = values['kind']
        parts = row.get('compositions') or {}
        composition = parts.get(kind) or parts.get(kind.removeprefix('rate:'))
        if composition is None:
            raise ValidationError('构成未随本次汇总生成，请重新查询汇总。')
        result = {**composition, 'query_context': parent.pk}
        if kind.startswith('rate:'):
            result = {key: value for key, value in result.items() if key != 'cost'}
            result.update(title='费率 · ' + result['title'], records=[], records_total=0)
        response = success_response(result)
        response['Cache-Control'] = 'no-store'
        return response
    payload = {**logical_payload(parent.request), 'action': 'table_detail'}
    for key in ('row_key', 'kind', 'source_key', 'cost_page', 'flow_page'):
        if key in detail.validated_data:
            payload[key] = detail.validated_data[key]
    data = job_data(request_calculation(dataset, request.user, payload), request.user)
    response = success_response(data['result'] if data.get('result') is not None else data,
                                status=202 if data['pending'] else 200)
    response['Cache-Control'] = 'no-store'
    return response


class FeeInput(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    record = serializers.JSONField()


@api_view(['POST'])
@permission_classes([IsFinanceViewer])
def summary_fee(request, pk):
    from .summary_service import require_access
    dataset = dataset_for(request.user, pk)
    require_access(request.user, write=True)
    data = FeeInput(data=request.data)
    data.is_valid(raise_exception=True)
    record = data.validated_data['record']
    allowed = {'id', 'store', 'month', 'date', 'kind', 'mode', 'order', 'amount', 'reason', 'operation'}
    if not isinstance(record, dict) or set(record) - allowed or len(json.dumps(record)) > 10000:
        raise ValidationError('费用字段无效。')
    if data.validated_data['revision'] != dataset.accounting_state.revision:
        return error_response('FINANCE_REVISION_CONFLICT', '其他操作已更新此批次，请刷新后重新修改。', status=409)
    action = 'prepare_participation' if record.get('operation') in {'exclude_source', 'restore_source'} else 'prepare_fee'
    prepared = engine(dataset, {'action': action, 'state': unpack_values(dataset.accounting_state.values), 'record': record})
    saved = save_state(dataset, request.user, revision=data.validated_data['revision'], reason=record.get('reason', ''), **prepared)
    if saved is None:
        return error_response('FINANCE_REVISION_CONFLICT', '其他操作已更新此批次，请刷新后重新修改。', status=409)
    return success_response({'dataset': saved['dataset'], 'revision': saved['revision']}, '费用已保存，各级汇总已更新。')


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
@request_access
def summary_history(request, pk):
    dataset = dataset_for(request.user, pk)
    payload = TableInput(data=request.query_params)
    payload.is_valid(raise_exception=True)
    return calculation_response(dataset, request.user, {'action': 'history', 'page': payload.validated_data['page']})
