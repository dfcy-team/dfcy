"""Permission-scoped, aggregate-only summaries for Feishu report delivery."""
import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.reports.datasets import DATASETS, query_dataset

REPORT_DATASETS = {
    "sales": ("sales",), "sales_skus": ("sales_skus",), "refunds": ("refunds",),
    "finance": ("finance",), "inventory": ("inventory",), "inventory_value": ("inventory_value",),
    "comprehensive": ("sales", "sales_skus", "refunds", "finance", "inventory", "inventory_value"),
}
METRICS = {
    "sales": ("order_count", "valid_order_count", "gross_sales"),
    # Do not add order_count: per-SKU distinct orders cannot be summed.
    "sales_skus": ("units_sold", "gross_sales", "unmapped_count"),
    "refunds": ("case_count", "requested_amount", "completed_amount", "unlinked_count"),
    "finance": ("transaction_count", "signed_amount", "unmatched_count", "unknown_count"),
    "inventory": ("sku_count", "on_hand", "available", "unmapped_count"),
    "inventory_value": ("sku_count", "valued_count", "missing_cost_count", "zero_cost_count", "inventory_value"),
}
MONEY_DATASETS = {key for key, metrics in METRICS.items() if any(DATASETS[key]["metrics"][m]["kind"] == "money" for m in metrics)}


def _value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _report_type(rule):
    config = _value(rule, "config", {}) or {}
    kind = _value(config, "report_type")
    if kind not in REPORT_DATASETS:
        raise ValidationError("不支持的飞书报表类型。")
    return kind, config


def _window(config):
    raw = config.get("filters") or {}
    if not isinstance(raw, dict) or set(raw) - {"date_from", "date_to"}:
        raise ValidationError("飞书报表仅支持日期窗口筛选。")
    try:
        supplied = {key: date.fromisoformat(str(raw[key])) for key in raw if raw.get(key)}
    except (TypeError, ValueError) as exc:
        raise ValidationError("日期格式应为 YYYY-MM-DD。") from exc
    today = timezone.localdate(timezone=timezone.get_fixed_timezone(480))
    schedule = config.get("schedule", "daily")
    if schedule == "weekly":
        default_from, default_to = today - timedelta(days=7), today - timedelta(days=1)
    elif schedule == "monthly":
        first = today.replace(day=1); default_to = first - timedelta(days=1); default_from = default_to.replace(day=1)
    else:
        default_from = default_to = today - timedelta(days=1)
    start, end = supplied.get("date_from", default_from), supplied.get("date_to", default_to)
    if start > end:
        raise ValidationError("开始日期不能晚于结束日期。")
    if (end - start).days > 30:
        raise ValidationError("飞书报表日期窗口最多 31 天。")
    return {"date_from": start.isoformat(), "date_to": end.isoformat()}


def _query(user, dataset, filters):
    dimensions = ["currency"] if dataset in MONEY_DATASETS else list(DATASETS[dataset]["defaults"]["dimensions"])
    scoped_filters = {"date_to": filters["date_to"]} if dataset.startswith("inventory") else filters
    raw = {"dataset": dataset, "dimensions": dimensions, "metrics": list(METRICS[dataset]), "filters": scoped_filters}
    return query_dataset(SimpleNamespace(user=user), raw, use_cache=False)


def _iso(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value else "未知"


def _range(result, dataset):
    filters = result.get("config", {}).get("filters", {})
    return f"截至 {filters.get('date_to') or '生成时点'}" if dataset.startswith("inventory") else f"{filters.get('date_from')} 至 {filters.get('date_to')}"


def _sum_rows(dataset, rows):
    metrics = METRICS[dataset]
    groups = {} if dataset in MONEY_DATASETS else {None: {key: 0 for key in metrics}}
    for row in rows:
        currency = (row.get("currency") or "未知币种") if dataset in MONEY_DATASETS else None
        total = groups.setdefault(currency, {key: Decimal("0") if DATASETS[dataset]["metrics"][key]["kind"] == "money" else 0 for key in metrics})
        for key in metrics:
            value = row.get(key) or 0
            total[key] += Decimal(str(value)) if DATASETS[dataset]["metrics"][key]["kind"] == "money" else value
    return [{**({"currency": currency} if currency is not None else {}), **values} for currency, values in sorted(groups.items(), key=lambda item: str(item[0]))]


def _section(dataset, result):
    return {"dataset": dataset, "title": DATASETS[dataset]["name"], "status": "available" if result.get("rows") else "no_data", "rows": _sum_rows(dataset, result.get("rows", [])),
            "data_range": _range(result, dataset), "as_of": _iso(result.get("refreshed_at")), "truncated": bool(result.get("truncated")), "note": DATASETS[dataset]["note"]}


def _summary(section):
    if section["status"] == "no_permission": return f"{section['title']}：无权限"
    if section["status"] == "unavailable": return f"{section['title']}：数据源不可用"
    if section["status"] == "no_data": return f"{section['title']}：{section['data_range']}暂无数据"
    parts = []
    for row in section["rows"]:
        prefix = f"{row['currency']} " if row.get("currency") else ""
        parts.append(prefix + "，".join(f"{DATASETS[section['dataset']]['metrics'][key]['label']} {value}" for key, value in row.items() if key != "currency"))
    return f"{section['title']}（{section['data_range']}）：" + "；".join(parts) + ("（结果已截断）" if section["truncated"] else "")


def build_report(rule, user) -> dict:
    """Build a non-PII aggregate report under the recipient's live authorization."""
    kind, config = _report_type(rule); filters = _window(config); sections = []; failures = []
    for dataset in REPORT_DATASETS[kind]:
        try:
            sections.append(_section(dataset, _query(user, dataset, filters)))
        except PermissionDenied:
            sections.append({"dataset": dataset, "title": DATASETS[dataset]["name"], "status": "no_permission", "message": "当前收件人无此数据范围权限。"})
        except Exception as exc:
            failures.append(exc); sections.append({"dataset": dataset, "title": DATASETS[dataset]["name"], "status": "unavailable", "message": "数据源暂不可用。"})
    accessible = [s for s in sections if s["status"] in {"available", "no_data"}]
    if not accessible:
        if failures: raise ValidationError("报表数据源暂不可用。")
        raise PermissionDenied("当前收件人没有可访问的报表数据源。")
    titles = {"comprehensive": "综合经营摘要", "sales": "销售摘要", "sales_skus": "SKU 商品销售摘要", "refunds": "退款退货摘要", "finance": "平台流水与费用摘要", "inventory": "库存摘要", "inventory_value": "库存估值摘要"}
    return {"title": titles[kind], "summary": "\n".join(_summary(section) for section in sections), "generated_at": timezone.localtime(timezone.now(), timezone.get_fixed_timezone(480)).isoformat(), "sections": sections}


def report_csv(report) -> bytes:
    """Return UTF-8 BOM CSV and neutralize spreadsheet formulas in every text cell."""
    output = io.StringIO(newline=""); writer = csv.writer(output)
    writer.writerow(["报表", report.get("title", "")]); writer.writerow(["生成时间", report.get("generated_at", "")]); writer.writerow(["数据集", "状态", "数据范围/截至", "截至时间", "币种", "指标", "数值", "说明"])
    for section in report.get("sections", []):
        if section.get("status") not in {"available", "no_data"}:
            writer.writerow([section.get("title", ""), section.get("status", ""), "", "", "", "", "", section.get("message", "")]); continue
        for row in section.get("rows") or [{}]:
            for key, value in row.items():
                writer.writerow([section.get("title", ""), section.get("status", ""), section.get("data_range", ""), section.get("as_of", ""), row.get("currency", ""), key, value, section.get("note", "")])
    safe = io.StringIO(newline=""); safe_writer = csv.writer(safe)
    for row in csv.reader(io.StringIO(output.getvalue())):
        safe_writer.writerow([("'" + cell if cell.lstrip().startswith(("=", "+", "-", "@")) else cell) for cell in row])
    return b"\xef\xbb\xbf" + safe.getvalue().encode("utf-8")
