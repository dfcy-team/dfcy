"""Same-day advertiser totals may prove zero; absent totals never do."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations import ads_sync


def response(*, total="0.00", info=None, rows=None):
    return {"list": [] if rows is None else rows, "page_info": info or {"page": 1, "total_page": 0, "total_number": 0},
            "total_metrics": {"spend": total}}


def collect(monkeypatch, aggregate, campaign=None):
    calls = []
    def get(_http, _path, params, _token):
        calls.append(params)
        assert params["report_type"] == "BASIC" and params["service_type"] == "AUCTION"
        assert params["start_date"] == params["end_date"] == "2026-10-16"
        return (campaign or {"list": [], "page_info": {"page": 1, "total_page": 0, "total_number": 0}}) if len(calls) == 1 else aggregate
    monkeypatch.setattr(ads_sync.pilot, "_get", get)
    renewals, proof = [], {}
    value = ads_sync.collect_day(None, SimpleNamespace(advertiser_id="123"), "SYNTHETIC", date(2026, 10, 16),
                                 lambda: renewals.append(True), proof=proof)
    return value, calls, proof, renewals


@pytest.mark.parametrize("total", ["0", "0.00", "0.000000", 0])
def test_explicit_advertiser_zero_is_proof(monkeypatch, total):
    value, calls, proof, renewals = collect(monkeypatch, response(total=total))
    assert value == Decimal("0") and len(calls) == len(renewals) == 2
    assert calls[1]["data_level"] == "AUCTION_ADVERTISER" and calls[1]["enable_total_metrics"] == "true"
    assert proof["source"] == "explicit_advertiser_total_zero"


@pytest.mark.parametrize("total", [None, "-", "", "1.00", "NaN", "-0", True, 0.0, "0.0000000"])
def test_missing_or_nonzero_or_invalid_total_stays_unknown(monkeypatch, total):
    value, _, proof, _ = collect(monkeypatch, response(total=total))
    assert value is None and not proof


@pytest.mark.parametrize("info", [{"page": 1, "total_page": 1, "total_number": 0},
    {"page": 2, "total_page": 0, "total_number": 0}, {"page": 1, "total_page": 0, "total_number": False},
    {"page": 1, "total_page": 0}, {"page": 1, "total_page": 0, "total_number": "0"}])
def test_unproven_pagination_blocks_zero(monkeypatch, info):
    assert collect(monkeypatch, response(info=info))[0] is None


def test_nonempty_summary_cannot_prove_empty_window(monkeypatch):
    assert collect(monkeypatch, response(rows=[{"metrics": {"spend": "0"}}]))[0] is None


def test_missing_campaign_total_does_not_attempt_fallback(monkeypatch):
    get = []
    def incomplete(*args):
        get.append(args)
        return {"list": [], "page_info": {"page": 1, "total_page": 0}}
    monkeypatch.setattr(ads_sync.pilot, "_get", incomplete)
    with pytest.raises(ValidationError, match="row count"):
        ads_sync.collect_day(None, SimpleNamespace(advertiser_id="123"), "SYNTHETIC",
            date(2026, 10, 16), lambda: None)
    assert len(get) == 1


def test_campaign_rows_need_no_advertiser_fallback(monkeypatch):
    value, calls, proof, _ = collect(monkeypatch, response(), campaign={"page_info": {"page": 1, "total_page": 1, "total_number": 1},
        "list": [{"dimensions": {"campaign_id": "9"}, "metrics": {"spend": "1.234567"}}]})
    assert value == Decimal("1.234567") and len(calls) == 1 and proof["source"] == "campaign_rows"
