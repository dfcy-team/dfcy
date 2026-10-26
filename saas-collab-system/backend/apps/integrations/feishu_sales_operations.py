"""A daily sales workbench digest built with the recipient's live sales grant."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.http import QueryDict
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
    return {'title': '昨日店铺经营日报', 'summary': '按授权店铺与来源币种汇总；今日同时段快照尚未就绪。',
            'sections': [], 'operations': data, 'generated_at': data['generated_at'],
            'suppress_delivery': not data['rows'], 'suppress_reason': 'NO_SALES_OBSERVATIONS'}


def operations_card(report, url_builder):
    from .feishu_report_cards import _markdown, _text, _number, bounded_card
    data = report['operations']
    def number(value, unit=''):
        numeric = _number(value)
        return '未就绪' if numeric is None else f'{numeric:,.2f}{unit}'
    filters = data['filters']
    path = '/sales-management/overview?' + urlencode({'view': 'operations', 'date_from': filters['date_from'], 'date_to': filters['date_to']})
    elements = [_markdown('观察日期：' + filters['date_from'] + '\n对比日期：' + filters['previous_from'] + '\n门店当地业务日期；按接收人当前销售权限生成。'),
                {'tag': 'button', 'text': {'tag': 'plain_text', 'content': '登录查看销售工作台'}, 'type': 'primary',
                 'behaviors': [{'type': 'open_url', 'default_url': url_builder(path)}]}]
    for group in data['currency_groups']:
        currency = _text(group['currency'])
        elements.append(_markdown('**' + currency + ' · 授权范围合计**\nGMV ' + number(group['sales_amount'], ' ' + currency) +
                                  ' · 较前日 ' + number(group['change_percent'], '%') + '\n整店ROI ' + number(group['roi'], ' 倍') +
                                  ' · ROI差值 ' + number(group['roi_delta'], ' 倍')))
    elements.append(_markdown('**店铺表现（最多20条，按GMV降序）**'))
    for row in data['rows']:
        elements.append(_markdown(_text(row['store_name']) + ' · ' + _text(row['country']) + '\nGMV ' + number(row['sales_amount'], ' ' + _text(row['currency'])) +
                                  ' · 较前日 ' + number(row['change_percent'], '%') + '\nROI ' + number(row['roi'], ' 倍') + ' · ' + _text(row['ad_reason'])))
    if data['has_next']:
        elements.append(_markdown('其余店铺请登录工作台查看；合计为完整授权查询范围，不是本页小计。'))
    elements.append(_markdown('只比较已入库数据，来源完整性未确认；缺失基准不补零。金额按非取消订单总额计算，含订单层费用。今日09:00同时段尚未接入，本卡仅含昨日全天。'))
    return bounded_card(report['title'], elements)
