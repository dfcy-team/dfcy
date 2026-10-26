"""Bounded period projections. Missing observations are never fabricated as zero."""
import calendar
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .datasets import DATASETS, normalize_config, query_dataset
from .aggregate_blocks import daily_blocks

METRICS = {
    "inventory": ["provided_on_hand", "provided_available", "provided_reserved", "sku_count", "provided_out_count", "unmapped_count"],
    "sales": ["gross_sales", "valid_order_count", "cancelled_order_count"],
    "sales_skus": ["gross_sales", "units_sold", "unmapped_count"],
    "finance": ["signed_amount", "transaction_count", "unmatched_count", "unknown_count"],
    "advertising": ["expense", "impressions", "clicks", "direct_gmv", "broad_gmv", "record_count"],
}


def normalize_analysis(raw, *, user=None):
    if not isinstance(raw, dict) or set(raw) - {"dataset", "mode", "year", "date_from", "date_to", "filters", "group_by"}:
        raise ValidationError("周期分析配置格式不正确。")
    dataset = raw.get("dataset", "sales")
    if not isinstance(dataset, str) or dataset not in METRICS or dataset not in DATASETS:
        raise ValidationError("请选择已接入的周期分析数据集。")
    mode = raw.get("mode", "monthly")
    if not isinstance(mode, str) or mode not in {"monthly", "weekly", "period"}:
        raise ValidationError("请选择月度、ISO 周度或自定义周期。")
    filters = raw.get("filters", {})
    if not isinstance(filters, dict) or {"date_from", "date_to"} & set(filters):
        raise ValidationError("日期必须通过周期条件指定。")
    if dataset == "inventory" and mode != "period":
        raise ValidationError("库存快照仅支持两个截止日期对比，不按销售周期累加。")
    dimensions = ["warehouse_id", "site_code"] if dataset == "inventory" else ["date", "currency"]
    config = normalize_config({"dataset": dataset, "dimensions": dimensions, "metrics": METRICS[dataset], "filters": filters})
    # Use a conservative common completed local date (UTC-12 is the last timezone).
    cutoff = (timezone.now() - timedelta(hours=12)).date() - timedelta(days=1)
    if user is not None:
        if dataset in {"sales", "sales_skus", "advertising"}:
            # Master-data lookup only: no fact-table scan in the submission request.
            # All tenant store timezones provide a conservative common boundary.
            from apps.masterdata.models import StoreMaster
            zones = list(StoreMaster.objects.filter(tenant=user.tenant).order_by().values_list("timezone", flat=True).distinct())
            try:
                if zones:
                    cutoff = min(timezone.now().astimezone(ZoneInfo(zone)).date() - timedelta(days=1) for zone in zones)
            except (ZoneInfoNotFoundError, TypeError, ValueError):
                pass  # retain the universally completed date for invalid master data
        else:
            cutoff = timezone.now().date() - timedelta(days=1)
    result = {"dataset": dataset, "mode": mode, "filters": config["filters"], "cutoff": cutoff.isoformat()}
    if raw.get("group_by"):
        if dataset not in {"sales", "advertising"} or not isinstance(raw["group_by"], str) or raw["group_by"] not in {"country", "platform", "store_id"}:
            raise ValidationError("分组仅支持销售或广告的国家、平台、店铺。")
        result["group_by"] = raw["group_by"]
    if mode == "period":
        try:
            start, end = date.fromisoformat(raw["date_from"]), date.fromisoformat(raw["date_to"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError("请选择有效起止日期。") from exc
        if start > end or (end - start).days > 365 or start.year < 2025:
            raise ValidationError("周期应在 2025 年以后，且不超过 366 天。")
        result.update(date_from=start.isoformat(), date_to=end.isoformat())
    else:
        year = raw.get("year", cutoff.year)
        if type(year) is not int or not 2025 <= year <= cutoff.year:
            raise ValidationError("请选择 2025 年至当前年份。")
        result["year"] = year
    return result


def _month_start(year, month):
    return date(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def _year_before(day):
    return day.replace(year=day.year - 1, day=min(day.day, calendar.monthrange(day.year - 1, day.month)[1]))


def period_slots(config):
    cutoff = date.fromisoformat(config["cutoff"])
    if config["mode"] == "period":
        start, end = date.fromisoformat(config["date_from"]), date.fromisoformat(config["date_to"])
        length = (end - start).days + 1
        spans = [("所选周期", start, end, _year_before(start), _year_before(end), start - timedelta(days=length), start - timedelta(days=1))]
    elif config["mode"] == "monthly":
        year = config["year"]
        spans = []
        for month in range(1, 13):
            start, end = _month_start(year, month), _month_start(year, month + 1) - timedelta(days=1)
            previous = _month_start(year, month - 1)
            spans.append((f"{month:02d}月", start, end, _month_start(year - 1, month), _month_start(year - 1, month + 1) - timedelta(days=1), previous, start - timedelta(days=1)))
    else:
        year = config["year"]
        spans = []
        for week in range(1, date(year, 12, 28).isocalendar().week + 1):
            start = date.fromisocalendar(year, week, 1)
            try:
                prior = date.fromisocalendar(year - 1, week, 1)
            except ValueError:
                prior = None
            spans.append((f"W{week:02d}", start, start + timedelta(days=6), prior, prior + timedelta(days=6) if prior else None, start - timedelta(days=7), start - timedelta(days=1)))
    result = []
    for label, start, end, yoy_start, yoy_end, previous_start, previous_end in spans:
        actual_end = min(end, cutoff)
        partial = start <= cutoff < end
        if partial:
            elapsed = actual_end - start
            yoy_end = min(yoy_end, yoy_start + elapsed) if yoy_start else None
            previous_end = min(previous_end, previous_start + elapsed)
        def window(left, right):
            return {"date_from": left.isoformat(), "date_to": right.isoformat()} if left and right and left <= right and right >= date(2025, 1, 1) else None
        result.append({"label": label, "start": start.isoformat(), "end": end.isoformat(), "partial": partial,
                       "future": start > cutoff, "current": window(start, actual_end),
                       "yoy": window(yoy_start, yoy_end) if start <= cutoff else None,
                       "previous": window(previous_start, previous_end) if start <= cutoff else None})
    return result


def _ratio(numerator, denominator, multiplier=1):
    return str(numerator / denominator * multiplier) if numerator is not None and denominator not in (None, 0) else None


def aggregate_window(rows, window, metrics, dataset):
    if not window:
        return None
    selected = [row for row in rows if window["date_from"] <= str(row["date"])[:10] <= window["date_to"]]
    if not selected:
        return None
    values = {}
    for key in metrics:
        observed = [Decimal(str(row[key])) for row in selected if row.get(key) is not None]
        values[key] = (sum(observed, Decimal(0)) if observed else None) if dataset == "advertising" else (
            sum(observed, Decimal(0)) if len(observed) == len(selected) else None
        )
    if dataset == "sales":
        values["average_order_value"] = _ratio(values["gross_sales"], values["valid_order_count"])
    elif dataset == "advertising":
        values.update(ctr=_ratio(values["clicks"], values["impressions"], 100), cpc=_ratio(values["expense"], values["clicks"]), direct_roas=_ratio(values["direct_gmv"], values["expense"]), broad_roas=_ratio(values["broad_gmv"], values["expense"]))
    return {"metrics": {key: str(value) if value is not None else None for key, value in values.items()}, "observed_days": len({str(row["date"])[:10] for row in selected}), "expected_days": (date.fromisoformat(window["date_to"]) - date.fromisoformat(window["date_from"])).days + 1, "coverage": "unverified"}


def build_analysis(request, config):
    if config["dataset"] == "inventory":
        return build_inventory_comparison(request, config)
    slots = period_slots(config)
    windows = [slot[key] for slot in slots for key in ("current", "yoy", "previous") if slot[key]]
    if not windows:
        return {"config": config, "series": [], "note": "所选周期尚未开始。"}
    filters = {**config["filters"], "date_from": max("2025-01-01", min(w["date_from"] for w in windows)), "date_to": max(w["date_to"] for w in windows)}
    # SQL daily aggregation, never loading individual orders. Reused for month/week queries.
    dimensions = ["date", "currency", *([config["group_by"]] if config.get("group_by") else [])]
    result = daily_blocks(request, {"dataset": config["dataset"], "dimensions": dimensions, "metrics": METRICS[config["dataset"]], "filters": filters})
    if result["truncated"]:
        raise ValidationError("数据分组超出安全范围，请筛选国家、店铺或币种后重试。")
    currencies = sorted({row.get("currency") or "未知币种" for row in result["rows"]})
    series = []
    for currency in currencies:
        rows = [row for row in result["rows"] if (row.get("currency") or "未知币种") == currency]
        points = []
        for slot in slots:
            point = {**slot, "drill": {key: {**config["filters"], **slot[key], "currency": currency} if slot[key] and currency != "未知币种" else None for key in ("current", "yoy", "previous")}}
            for key in ("current", "yoy", "previous"):
                point[key] = aggregate_window(rows, slot[key], METRICS[config["dataset"]], config["dataset"])
            point["changes"] = {}
            comparable_metrics = set(METRICS[config["dataset"]])
            for key in ("current", "yoy", "previous"):
                if point[key]:
                    comparable_metrics.update(point[key]["metrics"])
            for metric in sorted(comparable_metrics):
                current = point["current"]["metrics"].get(metric) if point["current"] else None
                point["changes"][metric] = {}
                for key in ("yoy", "previous"):
                    prior = point[key]["metrics"].get(metric) if point[key] else None
                    delta = Decimal(current) - Decimal(prior) if current is not None and prior is not None else None
                    # Percent change on a negative base is misleading (especially finance).
                    point["changes"][metric][key] = {"delta": str(delta) if delta is not None else None, "percent": _ratio(delta, Decimal(prior), 100) if prior is not None and Decimal(prior) > 0 else None}
            points.append(point)
        series.append({"currency": currency, "points": points})
    groups = []
    group_by = config.get("group_by")
    if group_by:
        for value, currency in sorted({(row[group_by], row.get("currency")) for row in result["rows"]}, key=str):
            rows = [row for row in result["rows"] if row[group_by] == value and row.get("currency") == currency]
            points = []
            for slot in slots:
                point = {"label": slot["label"], "start": slot["start"], "end": slot["end"], "partial": slot["partial"], "future": slot["future"], "drill": {}}
                for key in ("current", "yoy", "previous"):
                    point[key] = aggregate_window(rows, slot[key], METRICS[config["dataset"]], config["dataset"])
                    point["drill"][key] = {**config["filters"], **slot[key], "region" if group_by == "country" else group_by: value, "currency": currency} if slot[key] and value is not None and currency else None
                points.append(point)
            groups.append({"value": value, "label": result["dimension_labels"].get(group_by, {}).get(str(value), str(value or "未提供")), "currency": currency, "points": points})
    return {"config": config, "series": series, "groups": groups, "aggregate_blocks": result["aggregate_blocks"], "metric_version": result["metric_version"], "computed_at": result["computed_at"], "refreshed_at": result["refreshed_at"], "cached": result["cached"], "note": result["note"] + " 周期按已采集数据比较，完整性尚未逐店核验；无记录留空，不等于零销售。未结束周期按共同截止日及同进度比较；ISO 周年与自然年不同。近期汇总缓存最多 1 分钟，历史月份最多 1 小时；明细按实时数据重查，可能与本批次不同。", "coverage": "unverified"}


def build_inventory_comparison(request, config):
    cutoff = min(config["date_to"], config["cutoff"])
    if config["date_from"] > cutoff:
        raise ValidationError("请选择已结束的库存截止日期。")
    def snapshot(day):
        result = query_dataset(request, {"dataset": "inventory", "dimensions": ["warehouse_id", "site_code"], "metrics": METRICS["inventory"], "filters": {**config["filters"], "date_to": day}}, limit=2000)
        if result["truncated"]:
            raise ValidationError("仓库分组过多，请缩小仓库或站点范围。")
        return result
    prior, current = snapshot(config["date_from"]), snapshot(cutoff)
    previous = {(r["warehouse_id"], r["site_code"]): r for r in prior["rows"]}
    latest = {(r["warehouse_id"], r["site_code"]): r for r in current["rows"]}
    rows = []
    for key in sorted(previous.keys() | latest.keys(), key=str):
        before, after = previous.get(key), latest.get(key)
        rows.append({"warehouse_id": key[0], "site_code": key[1], "warehouse_name": current["dimension_labels"].get("warehouse_id", {}).get(str(key[0]), prior["dimension_labels"].get("warehouse_id", {}).get(str(key[0]), str(key[0]))), "current": after, "previous": before,
                     "delta": {metric: str(Decimal(str(after[metric])) - Decimal(str(before[metric]))) if before and after and before.get(metric) is not None and after.get(metric) is not None else None for metric in METRICS["inventory"]},
                     "drill": {"current": {**config["filters"], "warehouse_id": key[0], "site_code": key[1], "date_to": cutoff, "as_of": "true"}, "previous": {**config["filters"], "warehouse_id": key[0], "site_code": key[1], "date_to": config["date_from"], "as_of": "true"}}})
    return {"config": config, "rows": rows, "date_from": config["date_from"], "date_to": cutoff, "computed_at": current["computed_at"], "refreshed_at": current["refreshed_at"], "note": "各仓库、来源 SKU 取截止时点前最后快照；不同 SKU 的真实快照时间可能不同。差额不是出入库流水；缺失数量不按零处理。仓库库存不重复分配给店铺或平台。明细按实时数据重查，可能与本批次不同。"}
