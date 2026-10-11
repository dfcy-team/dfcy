import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.shopee_advertising import advertising_sync_scope
from apps.integrations.views import _validate_advertising_policy
from tests.test_shopee_advertising import SCOPE, campaign_page, client, response


def scope(*kinds):
    return {**SCOPE, "advertising_datasets": list(kinds)}


def test_shop_hourly_reads_one_day_per_cursor_without_campaign_requests():
    instance = client()
    instance._request.return_value = response([
        {"date": "01-10-2026", "hour": 0, "expense": 2, "direct_roas": 3},
        {"date": "01-10-2026", "hour": 23, "expense": 1},
    ])
    selected = scope("shop_hourly", "shop_toggle")
    result = instance.fetch_advertising(None, selected)
    assert [row["record_key"] for row in result["records"]] == [
        "shop_hourly:2026-10-01::0", "shop_hourly:2026-10-01::23"]
    assert result["records"][0]["campaign_id"] == ""
    assert result["records"][0]["data"] == {"expense": "2", "direct_roas": "3", "hour": 0}
    instance._request.assert_called_once_with(
        "/api/v2/ads/get_all_cpc_ads_hourly_performance", {"performance_date": "01-10-2026"})
    assert json.loads(result["next_cursor"]) == {"phase": "extra", "index": 0, "day": 1}
    instance._request.return_value = response([])
    for day in range(1, 7):
        result = instance.fetch_advertising(result["next_cursor"], selected)
        assert instance._request.call_args.args[1]["performance_date"] == f"0{day + 1}-10-2026"
    assert json.loads(result["next_cursor"]) == {"phase": "extra", "index": 1}
    assert result["raw_responses"][0]["endpoint"].endswith("get_all_cpc_ads_hourly_performance")


@pytest.mark.parametrize("rows", [
    [{"date": "01-10-2026", "hour": 24}],
    [{"date": "01-10-2026", "hour": True}],
    [{"date": "01-10-2026"}],
    [{"date": "02-10-2026", "hour": 0}],
    [{"date": "01-10-2026", "hour": 0}, {"date": "01-10-2026", "hour": 0}],
    [{"date": "01-10-2026", "hour": 0, "expense": "NaN"}],
])
def test_shop_hourly_rejects_invalid_or_duplicate_metrics(rows):
    instance = client()
    instance._request.return_value = response(rows)
    with pytest.raises(ValidationError):
        instance.fetch_advertising(None, scope("shop_hourly"))


def test_shop_hourly_selection_validates_and_finishes_empty_range():
    selected = advertising_sync_scope(SimpleNamespace(platform_config={}), scope("shop_hourly"))
    assert selected["advertising_datasets"] == ["shop_hourly"]
    instance = client()
    instance._request.return_value = response([])
    result = instance.fetch_advertising(json.dumps({"phase": "extra", "index": 0, "day": 6}), scope("shop_hourly"))
    assert result["records"] == [] and result["next_cursor"] == ""
    with pytest.raises(ValidationError):
        instance.fetch_advertising(json.dumps({"phase": "extra", "index": 0, "day": 7}), scope("shop_hourly"))


@pytest.mark.django_db
def test_shop_hourly_persistence_is_idempotent_and_distinct_from_other_grains():
    from apps.integrations.models import ShopeeAdvertisingRecord, SyncRun
    from apps.integrations.shopee_advertising import ShopeeAdvertisingAdapter
    from tests.test_sync_capability_gate import make_job
    job, auth = make_job()
    adapter = ShopeeAdvertisingAdapter(job.integration_config)
    adapter.authorization, adapter.scope = auth, SCOPE
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="shop-hourly-test", idempotency_key="shop-hourly-test")
    adapter.bind_run(run)
    instance = client()
    instance._request.return_value = response([{"date": "01-10-2026", "hour": 0, "expense": 2}])
    row = instance.fetch_advertising(None, scope("shop_hourly"))["records"][0]
    assert adapter.persist_record(job, row)["action"] == "created"
    assert adapter.persist_record(job, row)["action"] == "skipped"
    for kind in ("shop_daily", "campaign_hourly"):
        adapter.persist_record(job, {**row, "kind": kind, "record_key": row["record_key"].replace("shop_hourly", kind)})
    row["data"]["expense"] = "3"
    assert adapter.persist_record(job, row)["action"] == "updated"
    assert ShopeeAdvertisingRecord.objects.count() == 3
    stored = ShopeeAdvertisingRecord.objects.get(kind="shop_hourly")
    assert stored.source_run == run and stored.report_timezone == "Asia/Manila" and stored.currency == "PHP"
    assert stored.campaign_id == "" and stored.data["hour"] == 0


def test_hourly_paginates_days_and_preserves_hour_without_daily_collision():
    instance = client()
    hourly = {"shop_id": 456, "region": "PH", "campaign_list": [{"campaign_id": 11,
        "metrics_list": [{"date": "01-10-2026", "hour": 0, "expense": 2}]}]}
    instance._request.side_effect = [campaign_page(), response(hourly)]
    result = instance.fetch_advertising(None, scope("campaign_hourly"))
    assert result["records"][0]["record_key"] == "campaign_hourly:2026-10-01:11:0"
    assert result["records"][0]["data"] == {"expense": "2", "hour": 0}
    assert json.loads(result["next_cursor"])["day"] == 1
    assert instance._request.call_args.args[1] == {"performance_date": "01-10-2026", "campaign_id_list": "11"}


@pytest.mark.parametrize("change", [{"hour": 24}, {"hour": True}, {"date": "02-10-2026"}])
def test_hourly_rejects_unrequested_date_or_invalid_hour(change):
    instance = client()
    instance._request.side_effect = [campaign_page(), response({"shop_id": 456, "region": "PH",
        "campaign_list": [{"campaign_id": 11, "metrics_list": [{"date": "01-10-2026", "hour": 0, **change}]}]})]
    with pytest.raises(ValidationError):
        instance.fetch_advertising(None, scope("campaign_hourly"))


def test_gms_item_post_query_paginates_and_stores_period_not_daily():
    instance = client()
    instance._request.return_value = response({"campaign_id": 0, "total": 2, "has_next_page": True,
        "result_list": [{"item_id": 22, "report": {"expense": 2.3}}]})
    result = instance.fetch_advertising(None, scope("gms_item"))
    assert instance._request.call_args.kwargs["readonly_body"] == {
        "start_date": "01-10-2026", "end_date": "07-10-2026", "offset": 0, "limit": 100}
    record = result["records"][0]
    assert record["record_key"] == "gms_item:0:22:2026-10-01:2026-10-07"
    assert "report_date" not in record and record["data"]["period_start"] == "2026-10-01"
    assert json.loads(result["next_cursor"])["offset"] == 1
    instance._request.return_value = response({"campaign_id": 0, "total": 2, "has_next_page": False,
        "result_list": [{"item_id": 23, "report": {"expense": 1}}]})
    assert instance.fetch_advertising(result["next_cursor"], scope("gms_item"))["next_cursor"] == ""


@pytest.mark.parametrize("body", [
    {"campaign_id": 0, "result_list": [], "total": 2, "has_next_page": True},
    {"campaign_id": 0, "result_list": [], "total": 2, "has_next_page": False},
    {"campaign_id": 0, "result_list": [], "total": 0, "has_next_page": "false"},
    {"campaign_id": 0, "result_list": [{"item_id": 22, "report": {"expense": "NaN"}}], "total": 1, "has_next_page": False},
])
def test_gms_rejects_incomplete_and_invalid_reports(body):
    instance = client()
    instance._request.return_value = response(body)
    with pytest.raises(ValidationError):
        instance.fetch_advertising(None, scope("gms_item"))


def test_extra_only_reads_selected_snapshots_and_no_keyword_endpoint():
    instance = client()
    instance._request.side_effect = [response({"data_timestamp": 1790812800,
        "auto_top_up": False, "campaign_surge": True}), response([{"item_id": 22,
        "item_status_list": [], "sku_tag_list": ["best selling"], "ongoing_ad_type_list": []}])]
    selected = scope("shop_toggle", "recommended_item")
    first = instance.fetch_advertising(None, selected)
    second = instance.fetch_advertising(first["next_cursor"], selected)
    assert first["records"][0]["data"]["auto_top_up"] is False
    assert second["records"][0]["data"]["item_id"] == "22"
    assert second["next_cursor"] == ""
    assert [call.args[0] for call in instance._request.call_args_list] == [
        "/api/v2/ads/get_shop_toggle_info", "/api/v2/ads/get_recommended_item_list"]


def test_gms_campaign_keeps_aggregate_metrics():
    instance = client()
    instance._request.return_value = response({"campaign_id": 33, "report": {"expense": 1.2}})
    record = instance.fetch_advertising(None, scope("gms_campaign"))["records"][0]
    assert record["campaign_id"] == "33" and record["data"]["expense"] == "1.2"
    assert "direct_gmv" not in record["data"]


@pytest.mark.parametrize("datasets", [[], ["recommended_keyword"], ["edit_manual_product_ads"], "gms_item"])
def test_dataset_validation_rejects_excluded_keyword_and_writes(datasets):
    with pytest.raises(ValidationError):
        advertising_sync_scope(SimpleNamespace(platform_config={}), {"advertising_datasets": datasets})


def test_ads_policy_cannot_be_applied_to_order_jobs():
    with pytest.raises(ValidationError):
        _validate_advertising_policy(SimpleNamespace(resource_type="sales_order"), {"advertising_datasets": ["gms_item"]})


def test_gms_transport_signed_readonly_post_and_write_rejection(monkeypatch):
    from tests.test_shopee_readonly_runtime import configured
    from urllib.parse import parse_qs, urlsplit
    base, http = configured(monkeypatch, {"contract_approved": True, "api_host": "https://approved.example.test"})
    http.request.return_value.json.return_value = response({"campaign_id": 0, "report": {}})
    body = {"start_date": "01-10-2026", "end_date": "07-10-2026"}
    base._request("/api/v2/ads/get_gms_campaign_performance", {}, readonly_body=body)
    call = http.request.call_args
    assert call.args[0] == "POST" and call.kwargs["json_body"] == body
    assert parse_qs(urlsplit(call.args[1]).query)["shop_id"] == ["456"]
    assert "access_token" not in call.kwargs["json_body"]
    with pytest.raises(ValidationError, match="not allowed"):
        base._request("/api/v2/ads/edit_gms_product_campaign", {}, readonly_body={})
    assert http.request.call_count == 1


@pytest.mark.django_db
def test_extra_sync_engine_persists_selected_reports_with_source_run():
    from apps.integrations.models import ConnectionCapability, ShopeeAdvertisingRecord
    from apps.integrations.shopee_advertising import ShopeeAdvertisingAdapter
    from apps.integrations.sync_services import run_sync_job
    from tests.test_sync_capability_gate import make_job
    job, auth = make_job()
    config = job.integration_config
    config.environment = "production"
    config.platform_config = {"api_type": "advertising"}
    config.save()
    job.resource_type = "advertising_report"
    job.sync_scope = {"query": {"mode": "range", "start_at": "2026-10-01", "end_at": "2026-10-07",
        "advertising_datasets": ["gms_campaign", "shop_toggle", "recommended_item"]}}
    job.save()
    ConnectionCapability.objects.create(authorization=auth, capability_code="ADVERTISING", read_enabled=True,
        write_enabled=False, status="active")
    instance = client()
    instance.authorization = auth
    instance.preflight = Mock()
    instance._request.side_effect = [response({"campaign_id": 33, "report": {"expense": 1}}),
        response({"data_timestamp": 1790812800, "auto_top_up": False, "campaign_surge": False}),
        response([{"item_id": 22, "item_status_list": [], "sku_tag_list": [], "ongoing_ad_type_list": []}])]
    run, created = run_sync_job(job, adapter=ShopeeAdvertisingAdapter(config, client=instance), idempotency_key="ads-extra-test")
    assert created and run.status == "success" and run.created_count == 3
    assert ShopeeAdvertisingRecord.objects.filter(source_run=run).count() == 3
    assert run.masked_log["runtime_budget"]["resolved_scope"]["advertising_datasets"] == ["gms_campaign", "shop_toggle", "recommended_item"]
