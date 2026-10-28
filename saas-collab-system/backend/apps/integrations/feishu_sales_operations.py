"""A daily sales workbench digest built with the recipient's live sales grant."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.http import QueryDict
from django.db import DatabaseError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.permissions.services import check_user_permission
from apps.sales_management.sales_operations import _payload


def build_operations_report(user, filters, store_ids=None):
    if filters['date_from'] != filters['date_to']:
        raise ValidationError('经营日报只支持单个已结束日期。')
    if not check_user_permission(user, 'sales_management.view'):
        raise PermissionDenied('收件人没有销售工作台查看权限。')
    query = QueryDict('', mutable=True)
    query.update({**filters, 'view': 'stores', 'page': '1', 'page_size': '20'})
    data = _payload(SimpleNamespace(user=user, query_params=query, delivery_store_ids=store_ids))
    current_query = QueryDict('', mutable=True)
    current_query.update({'period': 'current', 'view': 'stores', 'page': '1', 'page_size': '20'})
    for key in ('platform', 'store_id', 'region', 'currency'):
        if filters.get(key) is not None:
            current_query[key] = str(filters[key])
    current, current_error = None, ''
    try:
        with transaction.atomic():
            current = _payload(SimpleNamespace(user=user, query_params=current_query, delivery_store_ids=store_ids))
    except (DatabaseError, ValidationError, PermissionDenied):
        current_error = '今日累计取数暂不可用，请登录查看或稍后重试。'
    return {'title': '店铺经营日报 · 全天与今日累计', 'summary': '按授权店铺与来源币种汇总；今日仅展示当前已入库数据。',
            'sections': [], 'operations': data, 'generated_at': data['generated_at'],
            'current_operations': current, 'current_error': current_error,
            'suppress_delivery': not data['rows'] and not (current and current['rows']) and not current_error,
            'suppress_reason': 'NO_SALES_OBSERVATIONS'}


def operations_card(report, url_builder):
    from .feishu_report_cards import _markdown, _text, _number, bounded_card
    data = report['operations']
    current = data.get('period') == 'current'
    def number(value, unit=''):
        numeric = _number(value)
        return '数据拉取不全，暂无法计算' if numeric is None else f'{numeric:,.2f}{unit}'
    filters = data['filters']
    detail_filters = {'view': 'operations', 'date_from': filters['date_from'], 'date_to': filters['date_to']}
    if current:
        detail_filters = {'view': 'operations', 'period': 'current'}
    for key in ('platform', 'store_id', 'region', 'currency'):
        value = filters.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and value != '':
            detail_filters[key] = value
    path = '/sales-management/overview?' + urlencode(detail_filters)
    observation = ('今日累计 · 各店当地零点至取数时刻；缺历史同点基准。' if current else '观察日期：' + filters['date_from'] + '\n对比日期：' + filters['previous_from'])
    elements = [_markdown(observation + '\n按接收人当前销售权限生成。'),
                {'tag': 'button', 'text': {'tag': 'plain_text', 'content': '查看今日累计明细' if current else '查看全天明细'}, 'type': 'primary',
                 'behaviors': [{'type': 'open_url', 'default_url': url_builder(path)}]}]
    for group in data['currency_groups']:
        currency = _text(group['currency'])
        elements.append(_markdown('**' + currency + ' · 授权范围合计**\nGMV ' + number(group['sales_amount'], ' ' + currency) +
                                  (' · 缺历史同点基准' if current else ' · 较前日 ' + number(group['change_percent'], '%')) + '\n整店ROI ' + (number(group['roi'], ' 倍') if group['roi'] is not None else _text(group.get('ad_reason') or '数据拉取不全，暂无法计算')) +
                                  ' · ROI差值 ' + (number(group['roi_delta'], ' 倍') if group['roi_delta'] is not None else _text(group.get('ad_reason') if group['roi'] is None else '缺少可比前期ROI')) + '\n' + _text(group.get('ad_reason', '数据拉取不全，按已入库数据暂估。'))))
    elements.append(_markdown('**店铺表现（最多20条，按GMV降序）**'))
    for row in data['rows']:
        elements.append(_markdown(_text(row['store_name']) + ' · ' + _text(row['country']) + '\nGMV ' + number(row['sales_amount'], ' ' + _text(row['currency'])) +
                                  (' · 缺历史同点基准' if current else ' · 较前日 ' + number(row['change_percent'], '%')) + '\nROI ' + (number(row['roi'], ' 倍') if row['roi'] is not None else _text(row.get('ad_reason') or '数据拉取不全，暂无法计算')) + ' · ' + _text(row['ad_reason'])))
    if data['has_next']:
        elements.append(_markdown('其余店铺请登录工作台查看；合计为完整授权查询范围，不是本页小计。'))
    elements.append(_markdown('仅已入库数据，来源完整性未确认；ROI 暂估。今日不与昨日全天比较，不代表09:00冻结快照。'))
    if report.get('current_operations'):
        current_card = operations_card({'title': '今日累计', 'operations': report['current_operations']}, url_builder)
        elements.extend([{'tag': 'hr'}, _markdown('**今日累计**'), *current_card['body']['elements']])
    elif report.get('current_error'):
        elements.append(_markdown(report['current_error']))
    return bounded_card(report['title'], elements)
