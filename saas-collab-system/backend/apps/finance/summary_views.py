import gzip
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response, error_response
from apps.permissions.api_permissions import IsFinanceViewer
from .summary_service import dataset_for, metadata, save_state, engine, document_path, unpack_values


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
def summary_bootstrap(request):
    dataset = dataset_for(request.user)
    data = metadata(dataset, request.user, include_values=request.query_params.get('native') != '1')
    data['document_version'] = hashlib.sha256(repr(presentation_stamp()).encode()).hexdigest()[:16]
    response = success_response(data)
    response['Cache-Control'] = 'no-store'
    return response


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
    return calculation_response(dataset, request.user, {'revision': data}, kind='rebuild')


def calculation_response(dataset, user, payload, *, kind='query'):
    from .summary_jobs import request_calculation, job_data
    data = job_data(request_calculation(dataset, user, payload, kind=kind), user)
    response = success_response(data['result'] if data.get('result') is not None else data,
                                status=202 if data['pending'] else 200)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
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
    from .summary_database_document import compact_browser_inputs
    html = compact_browser_inputs(html)
    from .summary_composition import adapt_document
    html = adapt_document(html)
    bridge = Path(__file__).with_name('summary_bridge.js').read_text(encoding='utf-8')
    runtime = Path(__file__).with_name('summary_runtime.js').read_text(encoding='utf-8')
    tools = Path(__file__).with_name('summary_tools.js').read_text(encoding='utf-8')
    def adapt(match):
        attrs, source = match.groups()
        if 'application/json' in attrs:
            return match.group(0)
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
    html = html.replace('<head>', '<head><script>'+runtime+'</script><script>'+tools+'</script><script>'+bridge+'</script>', 1)
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
                 [Path(__file__), Path(__file__).with_name('summary_database_document.py'), Path(__file__).with_name('summary_bridge.js'), Path(__file__).with_name('summary_runtime.js'), Path(__file__).with_name('summary_tools.js'), Path(__file__).with_name('summary_composition.py'), Path(__file__).with_name('summary_composition.js')])


@lru_cache(maxsize=2)
def prepared_document(path, source_hash, source_stamp, presentation_version):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as file:
        original = file.read()
    if hashlib.sha256(original.encode('utf-8')).hexdigest() != source_hash:
        raise ValidationError('财务批次来源校验失败，请恢复原始批次。')
    return gzip.compress(browser_document(original).encode('utf-8'), compresslevel=1)


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
def summary_document(request, pk):
    from django.http import HttpResponse
    dataset = dataset_for(request.user, pk)
    path = document_path(dataset)
    stamp = path.stat()
    body = prepared_document(str(path), dataset.source_hash, (stamp.st_mtime_ns, stamp.st_size), presentation_stamp())
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
def summary_report(request, pk):
    dataset = dataset_for(request.user, pk)
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
def summary_table(request, pk):
    dataset = dataset_for(request.user, pk)
    return calculation_response(dataset, request.user, {'action': 'table', **table_input(request)})


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
def summary_table_detail(request, pk):
    dataset = dataset_for(request.user, pk)
    payload = table_input(request)
    if not payload.get('row_key') or not payload.get('kind'):
        raise ValidationError('请选择金额或费率。')
    return calculation_response(dataset, request.user, {'action': 'table_detail', **payload})


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
    prepared = engine(dataset, {'action': 'prepare_fee', 'state': unpack_values(dataset.accounting_state.values), 'record': record})
    saved = save_state(dataset, request.user, revision=data.validated_data['revision'], reason=record.get('reason', ''), **prepared)
    if saved is None:
        return error_response('FINANCE_REVISION_CONFLICT', '其他操作已更新此批次，请刷新后重新修改。', status=409)
    return success_response({'dataset': saved['dataset'], 'revision': saved['revision']}, '费用已保存，各级汇总已更新。')


@api_view(['GET'])
@permission_classes([IsFinanceViewer])
def summary_history(request, pk):
    dataset = dataset_for(request.user, pk)
    payload = TableInput(data=request.query_params)
    payload.is_valid(raise_exception=True)
    return calculation_response(dataset, request.user, {'action': 'history', 'page': payload.validated_data['page']})
