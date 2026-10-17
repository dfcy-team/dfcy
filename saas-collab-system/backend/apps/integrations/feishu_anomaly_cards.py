"""Compact native cards for Top3 GMV and Top6 advertising changes."""
from .feishu_report_cards import _markdown, _text, _number, _button, bounded_card
from .feishu_anomaly_reports import BASELINE_LABELS

METRIC_LABELS = {'gross_sales': 'GMV', 'expense': '广告花费', 'roas': 'ROAS（广泛归因）'}


def _amount(value, unit):
    return '不可计算' if value is None else f'{value:,.2f} {unit}'


def _chart(metric, observed, comparisons, unit):
    values = []
    if _number(observed) is not None:
        values.append({'country': '昨日', 'value': _number(observed)})
    for c in comparisons:
        if _number(c['value']) is not None:
            values.append({'country': BASELINE_LABELS[c['baseline']], 'value': _number(c['value'])})
    return {'tag': 'chart', 'chart_spec': {'type': 'bar', 'data': {'values': values}, 'xField': 'country', 'yField': 'value',
            'title': {'visible': True, 'text': METRIC_LABELS[metric] + '对比（' + unit + '）'},
            'axes': [{'orient': 'left', 'title': {'visible': True, 'text': unit}}, {'orient': 'bottom', 'title': {'visible': True, 'text': '昨日与三个基准'}}],
            'label': {'visible': True}, 'legends': {'visible': False}}}


def anomaly_card(report, url_builder):
    data = report['anomalies']
    elements = [_markdown('观察日：' + _text(data['date']) + ' · 异常阈值：增减30%\n' + _text(data['quality_note'], 350))]
    for rank, item in enumerate(data['items'], 1):
        elements += [{'tag': 'hr'}, _markdown('**' + str(rank) + '. ' + _text(item['store_name']) + '** · ' + _text(item['country']) + ' (' + _text(item['country_code']) + ') · ' + _text(item['currency']))]
        for metric, observed in item['observations'].items():
            unit = '倍' if metric == 'roas' else item['currency']
            lines = ['**昨日' + METRIC_LABELS[metric] + '：' + _amount(observed, _text(unit)) + '**']
            for c in item['comparisons'][metric]:
                value = _amount(c['value'], _text(unit))
                pct = f"{c['change_percent']:+.1f}%" if c['change_percent'] is not None else '不可判定'
                flag = ' · 达到30%（待核验）' if c['observed_threshold_met'] else ''
                dates = c['dates'][0] if len(c['dates']) == 1 else c['dates'][0] + '～' + c['dates'][-1]
                reason = '（缺少基准日期）' if c['status'] == 'missing_dates' else '（零基准）' if c['status'] == 'zero_baseline' else ''
                lines.append(BASELINE_LABELS[c['baseline']] + ' ' + dates + '：' + value + ' · ' + pct + flag + reason)
            elements.append(_markdown('\n'.join(lines)))
            elements.append(_chart(metric, observed, item['comparisons'][metric], unit))
        section = {'dataset': data['dataset'], 'filters': {'date_from': data['date'], 'date_to': data['date'], 'store_id': item['store_id'], 'region': item['country_code'], 'currency': item['currency']}}
        elements.append(_button(section, url_builder))
    if not data['items']:
        elements.append(_markdown(data.get('message') or '当前已入库数据无可列入的店铺；不表示所有店铺采集完整或经营正常。'))
    if data.get('omitted_stores'):
        elements.append(_markdown('其余达到阈值的店铺 ' + str(data['omitted_stores']) + ' 家未列入本卡片。按最大绝对变化百分比排序，每店仅列一次。'))
    if data.get('stores_without_observation') or data.get('unusable_baselines'):
        elements.append(_markdown('存在观察日缺记录或基准不可用；缺失数据未按零计算。'))
    note = 'GMV沿用系统销售报表的非取消订单销售额口径（包含运费、税费），不是扣退款后净收入或利润。' if data['type'] == 'sales_anomalies' else '仅使用店铺级广告日报；ROAS=广泛归因GMV/花费。上周ROAS为周GMV总额/周花费总额；最近7天归因可能回补。'
    elements.append(_markdown(note + '\n来源记录最后更新时间：' + _text(data['source_refreshed_at']) + '\n报表生成时间：' + _text(report.get('generated_at', '未知'))))
    return bounded_card(report['title'], elements)
