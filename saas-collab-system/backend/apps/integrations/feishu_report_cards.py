"""Native Feishu JSON 2.0 charts from already recipient-scoped report data.

No database queries or image uploads here. Currency panels stay independent.
"""
import math
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from .feishu_reports import METRICS, _unit
from apps.reports.datasets import DATASETS

MAX_PANELS = 8
MAX_COUNTRIES = 6
MAX_BYTES = 28000
PRIMARY = {"sales": "gross_sales", "sales_skus": "units_sold", "inventory": "on_hand",
           "refunds": "requested_amount", "finance": "signed_amount", "inventory_value": "inventory_value"}


def _text(value, limit=160):
    # Provider Markdown must never interpret source labels as links, mentions,
    # images, or formatting. The chart labels themselves are plain data values.
    text = str("" if value is None else value).replace("<", "＜").replace(">", "＞")
    return re.sub(r"([\\`*_\[\]()!#|~])", r"\\\1", text.replace("\n", " "))[:limit]


def detail_path(section):
    """Only supported dataset and date filters; no user/tenant IDs or credentials."""
    dataset = section.get("dataset")
    if dataset not in METRICS and dataset != 'advertising':
        return "/reports/basic"
    query = {"tab": "analysis", "feishu_dataset": dataset}
    for key, value in section.get("filters", {}).items():
        if key in {"date_from", "date_to"} and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
            query[key] = value
    for key, pattern in (("store_id", r"[1-9][0-9]{0,18}"), ("region", r"[A-Z]{2,3}"), ("currency", r"[A-Z]{3}")):
        value = section.get("filters", {}).get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and re.fullmatch(pattern, str(value)):
            query[key] = str(value)
    return "/reports/basic?" + urlencode(query)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        result = float(number)
        return result if math.isfinite(result) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _markdown(content):
    return {"tag": "markdown", "content": content}


def _button(section, url_builder):
    return {"tag": "button", "text": {"tag": "plain_text", "content": "登录查看详细报表"},
            "type": "primary", "behaviors": [{"type": "open_url", "default_url": url_builder(detail_path(section))}]}


def report_chart_card(report, url_builder):
    """Build a bounded native chart card; missing facts are never plotted as zero."""
    if 'operations' in report:
        from .feishu_sales_operations import operations_card
        return operations_card(report, url_builder)
    if "anomalies" in report:
        from .feishu_anomaly_cards import anomaly_card
        return anomaly_card(report, url_builder)
    elements = [_markdown("数据生成时间：" + _text(report.get("generated_at", "未知")) + "（北京时间）")]
    if "inventory_requirements" in report:
        data = report["inventory_requirements"]
        elements.append(_markdown("**库存数据提示**：以下显示已入库库存；商品未映射不阻断展示。断货、补货和到仓风险判断尚未就绪。"))
        if data.get('unmapped_item_rows') is not None:
            elements.append(_markdown('近7天未映射销售明细：' + str(data['unmapped_item_rows']) + ' 条；不影响以下库存数据。'))
    panels = 0
    for section in report.get("sections", []):
        dataset = section.get("dataset")
        elements.append({"tag": "hr"})
        elements.append(_markdown("**" + _text(section.get("title", "报表")) + "** · " + _text(section.get("data_range", ""))))
        if section.get("status") != "available" or dataset not in PRIMARY:
            status = {"no_permission": "当前收件人无此数据权限", "unavailable": "数据源暂不可用", "no_data": "本期无已入库数据"}
            note = status.get(section.get("status"), "暂无可展示图表")
            if section.get("source_latest_date"):
                note += "；当前权限下最新业务日期：" + _text(section["source_latest_date"])
            elements.append(_markdown(note))
            if section.get("status") == "no_data":
                elements.append(_button(section, url_builder))
            continue
        key = PRIMARY[dataset]
        groups = {}
        for row in section.get("rows", []):
            currency = row.get("currency", "")
            groups.setdefault(currency, []).append(row)
        for currency, rows in groups.items():
            if panels >= MAX_PANELS:
                elements.append(_markdown("更多国家或币种请登录查看详细报表；卡片展示已限制。"))
                break
            panels += 1
            values = []
            facts = []
            for row in rows[:MAX_COUNTRIES]:
                country = str(row.get("country") or "国家未设置")[:80]
                number = _number(row.get(key))
                if number is not None:
                    values.append({"country": country, "value": number})
                fact_metrics = METRICS[dataset]
                facts.append("**" + _text(country) + "**\n" + " · ".join(
                    _text(DATASETS[dataset]["metrics"][metric]["label"]) + "：" +
                    ("未提供" if row.get(metric) is None else _text(row[metric]) + " " + _text(_unit(dataset, metric, row)))
                    for metric in fact_metrics))
            elements.append(_markdown("\n\n".join(facts)))
            if values:
                unit = _unit(dataset, key, rows[0])
                label = DATASETS[dataset]["metrics"][key]["label"]
                elements.append({"tag": "chart", "chart_spec": {
                    "type": "bar", "data": {"values": values}, "xField": "country", "yField": "value",
                    "title": {"visible": True, "text": label + ("（" + unit + "）" if unit else "")},
                    "axes": [{"orient": "left", "title": {"visible": True, "text": unit}},
                             {"orient": "bottom", "title": {"visible": True, "text": "国家"}}],
                    "legends": {"visible": False}, "label": {"visible": True},
                }})
            else:
                elements.append(_markdown("来源未提供可绘制数值，未按零补齐。"))
            if len(rows) > MAX_COUNTRIES:
                elements.append(_markdown("国家展示已限制，完整范围请登录查看详细报表。"))
        if section.get("truncated"):
            elements.append(_markdown("查询结果已截断，图表只代表当前返回部分。"))
        elements.append(_markdown("数据截至/刷新：" + _text(section.get("as_of", "未知")) + "\n" + _text(section.get("note", ""), 300)))
        elements.append(_button(section, url_builder))
    return bounded_card(report.get("title", "报表"), elements)


def bounded_card(title, elements):
    card = {"schema": "2.0", "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": str(title)[:100]}, "template": "blue"},
            "body": {"elements": elements}}
    if len(json.dumps(card, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        tail = [_markdown("卡片内容已限制，完整数据请登录查看详细报表。"),
                _markdown("请通过本卡片已展示的详情入口登录系统查看完整数据。")]
        while elements and len(json.dumps({**card, "body": {"elements": elements + tail}}, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
            elements.pop()
        card["body"]["elements"] = elements + tail
    return card
