"""Shopee Ads readonly contract, with bounded pages and resumable cursors."""
import json
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .adapters import ProductionReadonlyAdapter
from .models import ShopeeAdvertisingRecord
from .readonly_clients import ShopeeReadonlyClient


SITE_ZONES = {
    "PH": "Asia/Manila", "MY": "Asia/Kuala_Lumpur", "SG": "Asia/Singapore",
    "TH": "Asia/Bangkok", "VN": "Asia/Ho_Chi_Minh", "ID": "Asia/Jakarta",
    "TW": "Asia/Taipei", "BR": "America/Sao_Paulo",
}
METRIC_FIELDS = frozenset({
    "impression", "clicks", "ctr", "expense", "direct_order", "broad_order",
    "direct_gmv", "broad_gmv", "direct_conversions", "broad_conversions",
    "direct_item_sold", "broad_item_sold", "cost_per_conversion",
    "direct_roas", "broad_roas", "direct_order_amount", "broad_order_amount",
    "direct_roi", "broad_roi", "direct_cir", "broad_cir", "cr", "direct_cr", "cpc", "cpdc",
})
CAMPAIGN_FIELDS = frozenset({
    "ad_type", "ad_name", "campaign_status", "bidding_method",
    "campaign_placement", "campaign_budget", "item_id_list",
})
DEFAULT_DATASETS = ["campaign", "campaign_daily", "shop_daily", "balance"]
EXTRA_DATASETS = ["shop_hourly", "campaign_hourly", "gms_campaign", "gms_item", "shop_toggle", "recommended_item"]
DATASETS = DEFAULT_DATASETS + EXTRA_DATASETS


def advertising_sync_scope(config, override=None, authorization=None):
    scope = dict((config.platform_config or {}).get("sync_scope") or {})
    if isinstance(override, dict):
        scope.update(override)
        scope.update(override.get("query") or {})
    region = str(getattr(authorization, "region", "") or "").upper()
    zone_name = SITE_ZONES.get(region, "Asia/Shanghai")
    zone = ZoneInfo(zone_name)
    today = timezone.now().astimezone(zone).date()
    try:
        mode = scope.get("mode", scope.get("query_mode", "incremental"))
        if mode == "range":
            start = date.fromisoformat(str(scope.get("start_at") or scope.get("range_start_at")))
            end = date.fromisoformat(str(scope.get("end_at") or scope.get("range_end_at")))
        elif mode == "incremental":
            days = scope.get("lookback_days", 7)
            if isinstance(days, bool) or str(int(days)) != str(days):
                raise ValueError()
            end = today
            start = today - timedelta(days=int(days) - 1)
        else:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValidationError("Shopee 广告采集须使用有效日期或整数回看天数。")
    month_index = today.year * 12 + today.month - 1 - 6
    year, month = divmod(month_index, 12)
    oldest = date(year, month + 1, min(today.day, monthrange(year, month + 1)[1]))
    if not 2 <= (end - start).days + 1 <= 30 or end > today or start < oldest:
        raise ValidationError("Shopee 广告日报须采集最近六个月内的 2～30 天，结束日期不能晚于今天。")
    datasets = scope.get("advertising_datasets", DEFAULT_DATASETS)
    if not isinstance(datasets, list) or not datasets or any(value not in DATASETS for value in datasets):
        raise ValidationError("请选择有效的广告数据类型。")
    return {
        "start_date": start.strftime("%d-%m-%Y"), "end_date": end.strftime("%d-%m-%Y"),
        "time_from": int(datetime.combine(start, time.min, zone).timestamp()),
        "time_to": int(datetime.combine(end, time.max, zone).timestamp()),
        "report_timezone": zone_name,
        "advertising_datasets": list(dict.fromkeys(datasets)),
    }


def _identifier(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValidationError("Shopee Ads returned an invalid campaign identifier.")
    return str(value)


def _list(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValidationError("Shopee Ads response does not match the readonly contract.")
    return value


def _metrics(row):
    result = {}
    for key in METRIC_FIELDS & row.keys():
        try:
            value = Decimal(str(row[key]))
            if isinstance(row[key], bool) or not value.is_finite() or value < 0:
                raise ValueError()
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Shopee Ads returned an invalid numeric metric.")
        result[key] = str(value)
    return result


def _campaign_data(row):
    result = {}
    for key in CAMPAIGN_FIELDS & row.keys():
        value = row[key]
        if key == "item_id_list":
            if not isinstance(value, list):
                raise ValidationError("Shopee Ads returned invalid campaign products.")
            value = [_identifier(item) for item in value]
        elif key == "campaign_budget":
            value = _metrics({"expense": value})["expense"]
        elif not isinstance(value, str):
            raise ValidationError("Shopee Ads returned invalid campaign metadata.")
        result[key] = value
    return result


class ShopeeAdvertisingReadonlyClient(ShopeeReadonlyClient):
    PREFIX = "/api/v2/ads/"

    def _ads_request(self, name, query, *, readonly_body=None):
        payload = self._request(self.PREFIX + name, query, **({"readonly_body": readonly_body} if readonly_body is not None else {}))
        if payload.get("warning"):
            raise ValidationError("Shopee Ads returned a partial-data warning; inspect the platform API log.")
        body = payload.get("response")
        if not isinstance(body, (dict, list)):
            raise ValidationError("Shopee Ads response is missing.")
        return body

    def _shop(self, body):
        if not isinstance(body, dict) or str(body.get("shop_id")) != str(self.authorization.platform_store_id):
            raise ValidationError("Shopee Ads response shop does not match the selected authorization.")
        if str(body.get("region", "")).upper() != str(self.authorization.region).upper():
            raise ValidationError("Shopee Ads response region does not match the selected authorization.")
        return body

    @staticmethod
    def _daily(row, kind, scope, campaign_id=""):
        try:
            day = datetime.strptime(row["date"], "%d-%m-%Y").date()
            start = datetime.strptime(scope["start_date"], "%d-%m-%Y").date()
            end = datetime.strptime(scope["end_date"], "%d-%m-%Y").date()
            if not start <= day <= end:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Shopee Ads returned a report date outside the requested range.")
        return {
            "kind": kind, "record_key": f"{kind}:{day}:{campaign_id}",
            "report_date": day.isoformat(), "campaign_id": campaign_id, "data": _metrics(row),
        }

    def fetch_advertising(self, cursor, scope):
        datasets = scope.get("advertising_datasets", DEFAULT_DATASETS)
        phases = (["campaigns"] if set(datasets) & {"campaign", "campaign_daily"} else [])
        phases += [kind for kind in ("shop_daily", "balance") if kind in datasets]
        if set(datasets) & set(EXTRA_DATASETS):
            phases.append("extra")
        try:
            state = json.loads(cursor) if cursor else {"phase": phases[0], "offset": 0}
            phase, offset = state["phase"], int(state.get("offset", 0))
            if phase not in phases or offset < 0:
                raise ValueError()
        except (TypeError, ValueError, KeyError, IndexError):
            raise ValidationError("Invalid Shopee Ads sync cursor.")
        if phase == "extra":
            from .shopee_advertising_extra import fetch_extra
            return fetch_extra(self, state, scope)
        records = []
        following = phases[phases.index(phase) + 1:]
        next_state = {"phase": following[0], "index": 0} if following else None
        if phase == "campaigns":
            body = self._shop(self._ads_request("get_product_level_campaign_id_list", {
                "ad_type": "all", "offset": offset, "limit": 100,
            }))
            campaigns = _list(body.get("campaign_list"))
            ids = [_identifier(row.get("campaign_id")) for row in campaigns]
            if len(ids) > 100 or len(set(ids)) != len(ids) or not isinstance(body.get("has_next_page"), bool):
                raise ValidationError("Shopee Ads returned invalid campaign pagination.")
            if body["has_next_page"] and not ids:
                raise ValidationError("Shopee Ads pagination did not advance.")
            if ids:
                query = {"campaign_id_list": ",".join(ids)}
            if ids and "campaign" in datasets:
                settings = self._shop(self._ads_request(
                    "get_product_level_campaign_setting_info", {**query, "info_type_list": "1,2,3,4"},
                ))
                seen = set()
                for row in _list(settings.get("campaign_list")):
                    campaign_id = _identifier(row.get("campaign_id"))
                    common = row.get("common_info")
                    if campaign_id not in ids or campaign_id in seen or not isinstance(common, dict):
                        raise ValidationError("Shopee Ads returned invalid campaign settings.")
                    seen.add(campaign_id)
                    data = _campaign_data(common)
                    auto = row.get("auto_bidding_info") or {}
                    if not isinstance(auto, dict):
                        raise ValidationError("Shopee Ads returned invalid auto bidding settings.")
                    if "roas_target" in auto:
                        data["roas_target"] = _metrics({"expense": auto["roas_target"]})["expense"]
                    records.append({"kind": "campaign", "record_key": f"campaign:{campaign_id}",
                                    "campaign_id": campaign_id, "data": data})
                if seen != set(ids):
                    raise ValidationError("Shopee Ads campaign settings are incomplete.")
            if ids and "campaign_daily" in datasets:
                performance = self._ads_request("get_product_campaign_daily_performance", {
                    **query, "start_date": scope["start_date"], "end_date": scope["end_date"],
                })
                groups = [performance] if isinstance(performance, dict) else _list(performance)
                for group in groups:
                    self._shop(group)
                    for campaign in _list(group.get("campaign_list")):
                        campaign_id = _identifier(campaign.get("campaign_id"))
                        if campaign_id not in ids:
                            raise ValidationError("Shopee Ads returned an unrequested campaign.")
                        for row in _list(campaign.get("metrics_list")):
                            record = self._daily(row, "campaign_daily", scope, campaign_id)
                            record["data"].update(_campaign_data(campaign))
                            records.append(record)
            if body["has_next_page"]:
                next_state = {"phase": "campaigns", "offset": offset + len(ids)}
        elif phase == "shop_daily":
            body = self._ads_request("get_all_cpc_ads_daily_performance", {
                "start_date": scope["start_date"], "end_date": scope["end_date"],
            })
            records = [self._daily(row, "shop_daily", scope) for row in _list(body)]
        else:
            body = self._ads_request("get_total_balance", {})
            if not isinstance(body, dict):
                raise ValidationError("Shopee Ads returned an invalid balance.")
            try:
                stamp = int(body["data_timestamp"])
                amount = Decimal(str(body["total_balance"]))
                if stamp <= 0 or not amount.is_finite():
                    raise ValueError()
            except (KeyError, TypeError, ValueError, InvalidOperation):
                raise ValidationError("Shopee Ads returned an invalid balance.")
            records = [{"kind": "balance", "record_key": f"balance:{stamp}",
                        "data": {"data_timestamp": stamp, "total_balance": str(amount)}}]
        records = [row for row in records if row["kind"] in datasets]
        return {
            "records": records, "next_cursor": json.dumps(next_state) if next_state else "",
            # Archive only accepted fields, never credentials or signed URLs.
            "raw_responses": [
                {"endpoint": self.PREFIX + endpoint, "payload": {"records": [row for row in records if row["kind"] == kind]}}
                for kind, endpoint in (
                    [("campaign", "get_product_level_campaign_setting_info"),
                     ("campaign_daily", "get_product_campaign_daily_performance")]
                    if phase == "campaigns" else
                    [(phase, "get_all_cpc_ads_daily_performance" if phase == "shop_daily" else "get_total_balance")]
                )
                if kind in datasets
            ],
        }


class ShopeeAdvertisingAdapter(ProductionReadonlyAdapter):
    adapter_name = "shopee-advertising-readonly"

    def _client(self):
        if self.client is None:
            self.client = ShopeeAdvertisingReadonlyClient(self.config, self.authorization)
        self.client.resource_type = self.resource_type
        return self.client

    def validate_configuration(self, sync_job):
        super().validate_configuration(sync_job)
        if (self.config.platform_config or {}).get("api_type", "marketplace") != "advertising":
            raise ValidationError("Shopee 广告任务须选择广告 API 授权。")
        if self.authorization.region.upper() not in SITE_ZONES:
            raise ValidationError("Shopee 广告站点时区尚未支持。")
        self.scope = advertising_sync_scope(self.config, sync_job.sync_scope, self.authorization)

    def fetch_page(self, sync_job, cursor_value=None):
        return self._client().fetch_advertising(cursor_value, self.scope)

    def normalize_record(self, record):
        return record

    def persist_record(self, sync_job, record):
        auth = self.authorization
        store = auth.store
        values = {
            "kind": record["kind"], "report_date": record.get("report_date"),
            "campaign_id": record.get("campaign_id", ""), "currency": store.currency,
            "report_timezone": self.scope["report_timezone"], "data": record["data"],
            "dimensions": {"platform": "shopee", "store_id": str(store.pk), "country": auth.region},
        }
        if not store.currency:
            raise ValidationError("Shopee 广告店铺必须配置币种。")
        previous = ShopeeAdvertisingRecord.objects.filter(
            tenant=sync_job.tenant, store=store, record_key=record["record_key"],
        ).first()
        unchanged = previous and all(
            str(getattr(previous, key)) == str(value) if key == "report_date" else getattr(previous, key) == value
            for key, value in values.items()
        )
        if not unchanged:
            ShopeeAdvertisingRecord.objects.update_or_create(
                tenant=sync_job.tenant, store=store, record_key=record["record_key"],
                defaults={**values, "source_run": self._require_run()},
            )
        return {"action": "skipped" if unchanged else "updated" if previous else "created",
                "idempotency_key": f"{sync_job.pk}:{record['record_key']}"}
