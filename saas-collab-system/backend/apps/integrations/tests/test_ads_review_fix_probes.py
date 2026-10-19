"""No-DB regressions for strict Ads evidence, routing and retained scope."""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations import ads_sync, capability_gate


def mapping():
    return SimpleNamespace(pk=1, advertiser_id="123", timezone="Asia/Manila")


def report(page, count=3, ids=None):
    return {"page_info": {"page": page, "total_page": 2, "total_number": count},
            "list": [{"dimensions": {"campaign_id": str(i)}, "metrics": {"spend": "1"}}
                     for i in (ids if ids is not None else ([1, 2] if page == 1 else [3]))]}


@pytest.mark.parametrize("fault", ["missing_count", "disappearing_count", "changing_count",
    "missing_page", "wrong_page", "bool_page", "bool_count", "truncated_final"])
def test_campaign_proof_requires_every_page(monkeypatch, fault):
    monkeypatch.setattr(ads_sync.pilot, "REPORT_PAGE_SIZE", 2)
    def get(http, path, params, token):
        page = params["page"]
        data = report(page, count=4 if fault == "truncated_final" else 3)
        if fault == "missing_count" or fault == "disappearing_count" and page == 2:
            data["page_info"].pop("total_number")
        if fault == "changing_count" and page == 2:
            data["page_info"]["total_number"] = 4
        if fault == "missing_page":
            data["page_info"].pop("page")
        if fault == "wrong_page" and page == 2:
            data["page_info"]["page"] = 1
        if fault == "bool_page":
            data["page_info"]["page"] = True
        if fault == "bool_count":
            data["page_info"]["total_number"] = True
        return data
    monkeypatch.setattr(ads_sync.pilot, "_get", get)
    proof = {}
    with pytest.raises(ValidationError):
        ads_sync.collect_day(None, mapping(), "SYNTHETIC", date(2026, 9, 28), lambda: None, proof=proof)
    assert proof == {}


def test_complete_campaign_count_proves_nonempty_day(monkeypatch):
    monkeypatch.setattr(ads_sync.pilot, "REPORT_PAGE_SIZE", 2)
    monkeypatch.setattr(ads_sync.pilot, "_get", lambda h, p, q, t: report(q["page"]))
    proof = {}
    assert ads_sync.collect_day(None, mapping(), "SYNTHETIC", date(2026, 9, 28),
                               lambda: None, proof=proof) == Decimal("3")
    assert proof == {"source": "campaign_rows", "campaign_count": 3}


@pytest.mark.parametrize("explicit", [False, True])
def test_empty_campaigns_require_separate_advertiser_zero(monkeypatch, explicit):
    calls = []
    def get(http, path, params, token):
        calls.append(params["data_level"])
        data = {"page_info": {"page": 1, "total_page": 0, "total_number": 0}, "list": []}
        if params["data_level"] == "AUCTION_ADVERTISER" and explicit:
            data["total_metrics"] = {"spend": "0"}
        return data
    monkeypatch.setattr(ads_sync.pilot, "_get", get)
    proof = {}
    result = ads_sync.collect_day(None, mapping(), "SYNTHETIC", date(2026, 9, 28), lambda: None, proof=proof)
    assert result == (Decimal("0") if explicit else None)
    assert calls == ["AUCTION_CAMPAIGN", "AUCTION_ADVERTISER"]
    assert bool(proof) is explicit


@pytest.mark.parametrize("start,end", [("2024-12-30", "2024-12-31"), ("2024-12-31", "2025-01-02")])
def test_retention_floor_rejects_entire_and_crossing_ranges(start, end):
    with pytest.raises(ValidationError, match="retention floor"):
        ads_sync.resolve_scope(mapping(), {"query": {"mode": "range", "start_at": start, "end_at": end}})


def test_retention_exact_boundary_is_advertiser_local():
    scope = ads_sync.resolve_scope(mapping(), {"query": {"mode": "range",
        "start_at": "2025-01-01", "end_at": "2025-01-01"}},
        now=datetime(2025, 1, 1, 16, tzinfo=timezone.utc))
    assert scope["time_from"] == scope["time_to"] == "2025-01-01"


@pytest.mark.parametrize("fault", ["pre_floor", "crossing", "alias", "row_before", "row_after", "row_malformed"])
def test_persistence_revalidates_before_any_db_access(fault):
    adapter = ads_sync.AdsSpendAdapter(None)
    adapter.mapping = mapping()
    adapter.scope = ads_sync.resolve_scope(mapping(), {"query": {"mode": "range",
        "start_at": "2025-01-01", "end_at": "2025-01-02"}})
    rows = [{"date": "2025-01-01"}]
    if fault in {"pre_floor", "crossing"}:
        adapter.scope["time_from"] = "2024-12-31"
        if fault == "pre_floor":
            adapter.scope["time_to"] = "2024-12-31"
    elif fault == "alias":
        adapter.scope["start_date"] = "2024-12-31"
    else:
        rows.append({"date": {"row_before": "2024-12-31", "row_after": "2025-01-03",
                              "row_malformed": "20250101"}[fault]})
    with pytest.raises(ValidationError):
        adapter.persist_records(SimpleNamespace(), rows)


@pytest.mark.parametrize("platform,resource,code", [("shopee", "advertising_report", "ADVERTISING"),
    ("lazada", "sales_order", "ORDER"), ("tiktok", "sales_order", "ORDER")])
@pytest.mark.parametrize("enabled", [False, True])
def test_non_ads_mapping_routes_keep_existing_capability_gate(monkeypatch, platform, resource, code, enabled):
    job = SimpleNamespace(ads_mapping_id=None, integration_config=SimpleNamespace(platform=platform),
        resource_type=resource, store_authorization_id=7, store_authorization=SimpleNamespace(id=7, status="active"))
    capability = SimpleNamespace(authorization_id=7)
    query = Mock()
    query.first.return_value = capability if enabled else None
    selected = Mock(return_value=query)
    monkeypatch.setattr(capability_gate, "_eligible_source_queryset", selected)
    if enabled:
        assert capability_gate.require_sync_read_capability(job, "live_readonly") is capability
    else:
        with pytest.raises(ValidationError, match=f"CAPABILITY_NOT_ENABLED: {code}"):
            capability_gate.require_sync_read_capability(job, "live_readonly")
    selected.assert_called_once_with(job, code, lock=False)


def test_tiktok_advertising_without_mapping_still_fails():
    job = SimpleNamespace(ads_mapping_id=None, integration_config=SimpleNamespace(platform="tiktok"),
        resource_type="advertising_report", store_authorization_id=None, warehouse_authorization_id=None)
    with pytest.raises(ValidationError, match="exclusive advertiser mapping"):
        capability_gate.require_sync_read_capability(job, "live_readonly")


def test_mapping_routes_through_exclusive_validation(monkeypatch):
    job = SimpleNamespace(ads_mapping_id=1, resource_type="advertising_report",
        store_authorization_id=7, warehouse_authorization_id=None)
    with pytest.raises(ValidationError, match="exclusive advertiser mapping"):
        capability_gate.require_sync_read_capability(job, "live_readonly")
    job.store_authorization_id = None
    loaded = mapping()
    load = Mock(return_value=loaded)
    validate = Mock()
    monkeypatch.setattr(ads_sync, "load_mapping", load)
    monkeypatch.setattr(ads_sync, "validate_mapping", validate)
    assert capability_gate.require_sync_read_capability(job, "live_readonly", lock=True) is None
    load.assert_called_once_with(job, lock=True)
    validate.assert_called_once_with(loaded, lock=True)
