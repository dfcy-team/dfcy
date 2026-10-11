import json
from datetime import date, datetime, UTC
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.integrations.adapters import get_adapter_for_config
from apps.integrations.capability_gate import require_sync_read_capability
from apps.integrations.models import ConnectionCapability, ShopeeAdvertisingRecord, SyncRun
from apps.integrations.shopee_advertising import (
    ShopeeAdvertisingAdapter, ShopeeAdvertisingReadonlyClient, advertising_sync_scope,
)
from apps.integrations.sync_services import run_sync_job
from apps.permissions.models import DataScope, Permission, Role, UserRole
from tests.test_sync_capability_gate import make_job


SCOPE = {"start_date": "01-10-2026", "end_date": "07-10-2026", "report_timezone": "Asia/Manila"}


def client():
    instance = ShopeeAdvertisingReadonlyClient(SimpleNamespace(platform_config={}), custody=Mock(), http_client=Mock())
    instance.authorization = SimpleNamespace(platform_store_id="456", region="PH")
    instance._request = Mock()
    return instance


def response(value):
    return {"response": value}


def campaign_page(more=False):
    return response({"shop_id": 456, "region": "PH", "has_next_page": more,
                     "campaign_list": [{"campaign_id": 11, "ad_type": "manual"}]})


def settings_page():
    return response({"shop_id": 456, "region": "PH", "campaign_list": [
        {"campaign_id": 11, "common_info": {"ad_name": "Demo", "campaign_budget": 0, "item_id_list": [22]}}
    ]})


def performance_page():
    return response([{"shop_id": 456, "region": "PH", "campaign_list": [
        {"campaign_id": 11, "metrics_list": [{"date": "01-10-2026", "expense": 12.34,
                                            "direct_order": 0, "broad_order": 2}]}
    ]}])


@pytest.mark.parametrize("object_response", [False, True])
def test_five_get_contracts_and_resumable_pagination(object_response):
    instance = client()
    performance = performance_page()
    if object_response:
        performance["response"] = performance["response"][0]
    instance._request.side_effect = [
        campaign_page(True), settings_page(), performance,
        response({"shop_id": 456, "region": "PH", "has_next_page": False, "campaign_list": []}),
        response([{"date": "01-10-2026", "expense": 12.34, "broad_gmv": 30}]),
        response({"data_timestamp": 1790812800, "total_balance": 99.8}),
    ]
    first = instance.fetch_advertising(None, SCOPE)
    assert [row["kind"] for row in first["records"]] == ["campaign", "campaign_daily"]
    assert first["records"][1]["data"]["expense"] == "12.34"
    assert "clicks" not in first["records"][1]["data"]
    assert json.loads(first["next_cursor"])["offset"] == 1
    second = instance.fetch_advertising(first["next_cursor"], SCOPE)
    assert json.loads(second["next_cursor"])["phase"] == "shop_daily"
    third = instance.fetch_advertising(second["next_cursor"], SCOPE)
    final = instance.fetch_advertising(third["next_cursor"], SCOPE)
    assert final["records"][0]["data"]["total_balance"] == "99.8"
    assert final["next_cursor"] == ""
    calls = instance._request.call_args_list
    assert calls[0].args[1] == {"ad_type": "all", "offset": 0, "limit": 100}
    assert calls[1].args[1] == {"campaign_id_list": "11", "info_type_list": "1,2,3,4"}
    assert calls[3].args[1]["offset"] == 1
    assert len({call.args[0] for call in calls}) == 5
    assert "access_token" not in json.dumps(first["raw_responses"])


@pytest.mark.parametrize("body", [
    {"shop_id": 999, "region": "PH", "has_next_page": False, "campaign_list": []},
    {"shop_id": 456, "region": "MY", "has_next_page": False, "campaign_list": []},
    {"shop_id": 456, "region": "PH", "has_next_page": True, "campaign_list": []},
    {"shop_id": 456, "region": "PH", "has_next_page": False, "campaign_list": [{"campaign_id": 0}]},
    {"shop_id": 456, "region": "PH", "has_next_page": False, "campaign_list": [{"campaign_id": x} for x in range(1, 102)]},
])
def test_rejects_untrusted_campaign_pages(body):
    instance = client()
    instance._request.return_value = response(body)
    with pytest.raises(ValidationError):
        instance.fetch_advertising(None, SCOPE)
    assert instance._request.call_count == 1


def test_rejects_missing_settings_and_partial_warning():
    instance = client()
    instance._request.side_effect = [campaign_page(), response({"shop_id": 456, "region": "PH", "campaign_list": []})]
    with pytest.raises(ValidationError, match="incomplete"):
        instance.fetch_advertising(None, SCOPE)
    instance._request.side_effect = None
    instance._request.return_value = {"warning": "FAKE_TOKEN", "response": []}
    with pytest.raises(ValidationError) as error:
        instance.fetch_advertising(json.dumps({"phase": "shop_daily"}), SCOPE)
    assert "FAKE_TOKEN" not in str(error.value)


@pytest.mark.parametrize("row", [
    {"date": "01-01-2026", "expense": 1}, {"date": "01-10-2026", "expense": "NaN"},
    {"date": "01-10-2026", "clicks": -1}, {"expense": 1},
])
def test_rejects_bad_metrics_without_fabricating_zero(row):
    instance = client()
    instance._request.return_value = response([row])
    with pytest.raises(ValidationError):
        instance.fetch_advertising(json.dumps({"phase": "shop_daily"}), SCOPE)


@pytest.mark.parametrize("override", [
    {"query": {"lookback_days": 1}}, {"query": {"lookback_days": 31}},
    {"query": {"lookback_days": True}},
    {"query": {"mode": "range", "start_at": "2026-01-01", "end_at": "2026-01-07"}},
    {"query": {"mode": "range", "start_at": "2026-10-10", "end_at": "2026-10-12"}},
])
def test_scope_bounds(monkeypatch, override):
    monkeypatch.setattr("apps.integrations.shopee_advertising.timezone.now",
                        lambda: datetime(2026, 10, 9, 0, tzinfo=UTC))
    with pytest.raises(ValidationError):
        advertising_sync_scope(SimpleNamespace(platform_config={}), override)


def test_scope_uses_site_date_and_defaults_to_seven_days(monkeypatch):
    monkeypatch.setattr("apps.integrations.shopee_advertising.timezone.now",
                        lambda: datetime(2026, 10, 9, 0, tzinfo=UTC))
    scope = advertising_sync_scope(SimpleNamespace(platform_config={}), None, SimpleNamespace(region="BR"))
    assert scope["start_date"] == "02-10-2026"
    assert scope["end_date"] == "08-10-2026"
    assert scope["report_timezone"] == "America/Sao_Paulo"


def test_ads_resource_is_shopee_only():
    config = SimpleNamespace(environment="production", platform="shopee", platform_config={})
    assert isinstance(get_adapter_for_config(config, "advertising_report"), ShopeeAdvertisingAdapter)
    config.platform = "tiktok"
    assert get_adapter_for_config(config, "advertising_report").execution_mode == "unsupported"


def test_inherited_signer_only_calls_approved_get(monkeypatch):
    from tests.test_shopee_readonly_runtime import configured
    from urllib.parse import parse_qs, urlsplit
    base, http = configured(monkeypatch, {"contract_approved": True, "api_host": "https://approved.example.test"})
    instance = ShopeeAdvertisingReadonlyClient(base.config, base.authorization, custody=base.custody, http_client=http)
    instance.resource_type = "advertising_report"
    http.request.return_value.json.return_value = response({"data_timestamp": 1790812800, "total_balance": 1})
    instance.fetch_advertising(json.dumps({"phase": "balance"}), SCOPE)
    args = http.request.call_args.args
    assert args[0] == "GET"
    assert urlsplit(args[1]).path == "/api/v2/ads/get_total_balance"
    signed = parse_qs(urlsplit(args[1]).query)
    assert signed["shop_id"] == ["456"] and signed["access_token"] == ["FAKE_ACCESS"]
    assert len(signed["sign"][0]) == 64


@pytest.mark.django_db
def test_sync_engine_persists_three_phases_and_freezes_scope():
    job, auth = make_job()
    config = job.integration_config
    config.environment = "production"
    config.platform_config = {"api_type": "advertising"}
    config.save()
    job.resource_type = "advertising_report"
    job.sync_scope = {"query": {"mode": "range", "start_at": "2026-10-01", "end_at": "2026-10-07"}}
    job.save()
    ConnectionCapability.objects.create(authorization=auth, capability_code="ADVERTISING",
        read_enabled=True, write_enabled=False, status="active")
    instance = client()
    instance.authorization = auth
    instance.preflight = Mock()
    pages = [campaign_page(), settings_page(), performance_page(),
             response([{"date": "01-10-2026", "expense": 12}]),
             response({"data_timestamp": 1790812800, "total_balance": 99})]
    for page in pages[:3]:
        body = page["response"]
        (body if isinstance(body, dict) else body[0])["shop_id"] = auth.platform_store_id
    instance._request.side_effect = pages
    adapter = ShopeeAdvertisingAdapter(config, client=instance)
    run, created = run_sync_job(job, adapter=adapter, idempotency_key="ads-engine-key")
    assert created and run.status == "success"
    assert run.created_count == ShopeeAdvertisingRecord.objects.count() == 4
    assert run.masked_log["runtime_budget"]["resolved_scope"]["start_date"] == "01-10-2026"
    assert run.masked_log["runtime_budget"]["resolved_scope"]["report_timezone"] == "Asia/Manila"


@pytest.mark.django_db
def test_ads_gate_and_idempotent_persistence():
    job, auth = make_job()
    job.resource_type = "advertising_report"
    job.save()
    with pytest.raises(ValidationError, match="ADVERTISING"):
        require_sync_read_capability(job, "live_readonly")
    ConnectionCapability.objects.create(authorization=auth, capability_code="ADVERTISING",
        read_enabled=True, write_enabled=False, status="active")
    assert require_sync_read_capability(job, "live_readonly").write_enabled is False
    adapter = ShopeeAdvertisingAdapter(job.integration_config)
    adapter.authorization, adapter.scope = auth, SCOPE
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="ads-test-run", idempotency_key="ads-test-key")
    adapter.bind_run(run)
    row = {"kind": "shop_daily", "record_key": "shop_daily:2026-10-01:", "report_date": "2026-10-01", "data": {"expense": "10"}}
    assert adapter.persist_record(job, row)["action"] == "created"
    assert adapter.persist_record(job, row)["action"] == "skipped"
    row["data"]["expense"] = "11"
    assert adapter.persist_record(job, row)["action"] == "updated"
    assert ShopeeAdvertisingRecord.objects.count() == 1


@pytest.mark.django_db
def test_report_tenant_and_dimension_scope():
    job, auth = make_job()
    user = job.integration_config.created_by
    permission, _ = Permission.objects.get_or_create(code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    role = Role.objects.create(tenant=user.tenant, code="ads-view", name="Ads view")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    scope = DataScope.objects.create(tenant=user.tenant, role=role, scope_type="custom",
                                    config={"analytics_dimensions": [{"store_id": str(auth.store_id)}]})
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="ads-report-run", idempotency_key="ads-report-key")
    ShopeeAdvertisingRecord.objects.create(tenant=job.tenant, store=auth.store, source_run=run, kind="shop_daily",
        record_key="shop_daily:test", report_date=date(2026, 10, 1), currency="PHP", report_timezone="Asia/Manila",
        dimensions={"store_id": str(auth.store_id), "platform": "shopee"}, data={"expense": "12.3"})
    api = APIClient()
    api.force_authenticate(user)
    endpoint = "/api/internal/analytics/advertising/"
    result = api.get(endpoint)
    assert result.status_code == 200
    assert result.data["data"]["count"] == 1
    assert "token_id" not in json.dumps(result.data)
    for kind in ("shop_hourly", "campaign_hourly", "gms_campaign", "gms_item", "shop_toggle", "recommended_item"):
        ShopeeAdvertisingRecord.objects.create(tenant=job.tenant, store=auth.store, source_run=run, kind=kind,
            record_key=f"{kind}:test", report_date=date(2026, 10, 1) if kind.endswith("_hourly") else None,
            currency="PHP", report_timezone="Asia/Manila", dimensions={"store_id": str(auth.store_id)},
            data={"period_start": "2026-10-01", "period_end": "2026-10-07"} if kind.startswith("gms_") else {})
        assert api.get(endpoint, {"kind": kind}).data["data"]["count"] == 1
    assert api.get(endpoint, {"kind": "shop_hourly", "period_start": "2026-10-02"}).data["data"]["count"] == 0
    assert api.get(endpoint, {"kind": "shop_hourly", "period_end": "2026-09-30"}).data["data"]["count"] == 0
    assert api.get(endpoint, {"kind": "shop_hourly", "period_start": "2026-10-01", "period_end": "2026-10-01"}).data["data"]["count"] == 1
    assert api.get(endpoint, {"kind": "gms_item", "period_start": "2026-10-02"}).data["data"]["count"] == 0
    assert api.get(endpoint, {"kind": "gms_item", "period_start": "2026-10-01", "period_end": "2026-10-07"}).data["data"]["count"] == 1
    assert api.get(endpoint, {"kind": "recommended_keyword"}).status_code == 400
    scope.config = {"analytics_dimensions": [{"store_id": "999999"}]}
    scope.save()
    result = api.get(endpoint)
    assert result.data["data"]["count"] == 0
    assert result.data["data"]["stores"] == []
    assert api.post(endpoint, {}).status_code == 405
    api.force_authenticate(None)
    assert api.get(endpoint).status_code in {401, 403}
