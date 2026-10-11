"""Additional documented Ads queries; one bounded request page per cursor."""
import json
from datetime import datetime, timedelta

from rest_framework.exceptions import ValidationError

from .shopee_advertising import EXTRA_DATASETS, _identifier, _list, _metrics


def _integer(value, maximum=100000):
    if isinstance(value, bool) or not str(value).isdigit() or not 0 <= int(value) <= maximum:
        raise ValidationError("Shopee Ads returned an invalid integer.")
    return int(value)


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError("Shopee Ads returned invalid recommendation tags.")
    return value


def fetch_extra(client, state, scope):
    kinds = [kind for kind in EXTRA_DATASETS if kind in scope["advertising_datasets"]]
    index = _integer(state.get("index", 0), len(kinds))
    if index >= len(kinds):
        raise ValidationError("Invalid Shopee Ads dataset cursor.")
    kind = kinds[index]
    offset = _integer(state.get("offset", 0))
    records = []
    next_state = {"phase": "extra", "index": index + 1} if index + 1 < len(kinds) else None
    if kind == "shop_hourly":
        start = datetime.strptime(scope["start_date"], "%d-%m-%Y").date()
        end = datetime.strptime(scope["end_date"], "%d-%m-%Y").date()
        day = start + timedelta(days=_integer(state.get("day", 0), 29))
        if day > end:
            raise ValidationError("Invalid Shopee Ads hourly date cursor.")
        endpoint = "get_all_cpc_ads_hourly_performance"
        body = client._ads_request(endpoint, {"performance_date": day.strftime("%d-%m-%Y")})
        for row in _list(body):
            record = client._daily(row, kind, scope)
            if record["report_date"] != day.isoformat():
                raise ValidationError("Shopee Ads returned an unrequested hourly date.")
            hour = _integer(row.get("hour"), 23)
            record["record_key"] += f":{hour}"
            record["data"]["hour"] = hour
            records.append(record)
        if day < end:
            next_state = {"phase": "extra", "index": index, "day": (day-start).days + 1}
    elif kind == "campaign_hourly":
        start = datetime.strptime(scope["start_date"], "%d-%m-%Y").date()
        end = datetime.strptime(scope["end_date"], "%d-%m-%Y").date()
        day = start + timedelta(days=_integer(state.get("day", 0), 29))
        if day > end:
            raise ValidationError("Invalid Shopee Ads hourly date cursor.")
        campaigns = client._shop(client._ads_request("get_product_level_campaign_id_list", {
            "ad_type": "all", "offset": offset, "limit": 100,
        }))
        ids = [_identifier(row.get("campaign_id")) for row in _list(campaigns.get("campaign_list"))]
        if len(ids) > 100 or len(ids) != len(set(ids)) or type(campaigns.get("has_next_page")) is not bool:
            raise ValidationError("Shopee Ads returned invalid hourly campaign pagination.")
        if campaigns["has_next_page"] and not ids:
            raise ValidationError("Shopee Ads hourly pagination did not advance.")
        endpoint = "get_product_campaign_hourly_performance"
        if ids:
            body = client._ads_request(endpoint, {"performance_date": day.strftime("%d-%m-%Y"),
                "campaign_id_list": ",".join(ids)})
            groups = [body] if isinstance(body, dict) else _list(body)
            keys = set()
            for group in groups:
                client._shop(group)
                for campaign in _list(group.get("campaign_list")):
                    campaign_id = _identifier(campaign.get("campaign_id"))
                    if campaign_id not in ids:
                        raise ValidationError("Shopee Ads returned an unrequested hourly campaign.")
                    for row in _list(campaign.get("metrics_list")):
                        record = client._daily(row, kind, scope, campaign_id)
                        if record["report_date"] != day.isoformat():
                            raise ValidationError("Shopee Ads returned an unrequested hourly date.")
                        hour = _integer(row.get("hour"), 23)
                        record["record_key"] += f":{hour}"
                        record["data"]["hour"] = hour
                        if record["record_key"] in keys:
                            raise ValidationError("Shopee Ads returned duplicate hourly metrics.")
                        keys.add(record["record_key"])
                        records.append(record)
        if campaigns["has_next_page"]:
            next_state = {"phase": "extra", "index": index, "day": (day-start).days, "offset": offset + len(ids)}
        elif day < end:
            next_state = {"phase": "extra", "index": index, "day": (day-start).days + 1}
    elif kind in {"gms_campaign", "gms_item"}:
        endpoint = f"get_{kind}_performance"
        query = {"start_date": scope["start_date"], "end_date": scope["end_date"]}
        if kind == "gms_item":
            query.update(offset=offset, limit=100)
        body = client._ads_request(endpoint, {}, readonly_body=query)
        if not isinstance(body, dict):
            raise ValidationError("Shopee Ads returned invalid GMS report.")
        campaign_id = str(_integer(body.get("campaign_id"), 2**63 - 1))
        start = datetime.strptime(scope["start_date"], "%d-%m-%Y").date().isoformat()
        end = datetime.strptime(scope["end_date"], "%d-%m-%Y").date().isoformat()
        reports = _list(body.get("result_list")) if kind == "gms_item" else [body]
        ids = set()
        for row in reports:
            if not isinstance(row.get("report"), dict):
                raise ValidationError("Shopee Ads GMS metrics are missing.")
            item_id = _identifier(row.get("item_id")) if kind == "gms_item" else ""
            if item_id in ids:
                raise ValidationError("Shopee Ads returned duplicate GMS products.")
            ids.add(item_id)
            records.append({"kind": kind, "campaign_id": campaign_id,
                "record_key": f"{kind}:{campaign_id}:{item_id}:{start}:{end}",
                "data": {**_metrics(row["report"]), "item_id": item_id, "period_start": start, "period_end": end}})
        if kind == "gms_item":
            total = _integer(body.get("total"))
            more = body.get("has_next_page")
            if type(more) is not bool or len(reports) > 100 or offset + len(reports) > total:
                raise ValidationError("Shopee Ads returned invalid GMS pagination.")
            if more:
                if not reports or offset + len(reports) >= total:
                    raise ValidationError("Shopee Ads GMS pagination did not advance.")
                next_state = {"phase": "extra", "index": index, "offset": offset + len(reports)}
            elif offset + len(reports) != total:
                raise ValidationError("Shopee Ads GMS report is incomplete.")
    elif kind == "shop_toggle":
        endpoint = "get_shop_toggle_info"
        body = client._ads_request(endpoint, {})
        if not isinstance(body, dict) or any(type(body.get(key)) is not bool for key in ("auto_top_up", "campaign_surge")):
            raise ValidationError("Shopee Ads returned invalid toggle status.")
        stamp = _integer(body.get("data_timestamp"), 2**63 - 1)
        records = [{"kind": kind, "record_key": f"shop_toggle:{stamp}", "data": {
            "data_timestamp": stamp, "auto_top_up": body["auto_top_up"], "campaign_surge": body["campaign_surge"]}}]
    elif kind == "recommended_item":
        endpoint = "get_recommended_item_list"
        for row in _list(client._ads_request(endpoint, {})):
            item_id = _identifier(row.get("item_id"))
            records.append({"kind": kind, "record_key": f"recommended_item:{item_id}", "data": {
                "item_id": item_id, **{key: _strings(row.get(key)) for key in (
                    "item_status_list", "sku_tag_list", "ongoing_ad_type_list")}}})
    if len({row["record_key"] for row in records}) != len(records):
        raise ValidationError("Shopee Ads returned duplicate records.")
    return {"records": records, "next_cursor": json.dumps(next_state) if next_state else "",
        "raw_responses": [{"endpoint": client.PREFIX + endpoint, "payload": {"records": records}}]}
