from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.integrations.lazada_advertising import import_report_pair, sync_advertising
from apps.integrations.models import LazadaAdvertisingDailySpend, LazadaApiSnapshot
from tests.test_lazada_native_api import context


def pair(actor, auth, amounts=("12.10", "3.20")):
    params = {"startDate": "2026-09-01", "endDate": "2026-09-02", "useRtTable": False}
    overview = LazadaApiSnapshot.objects.create(
        tenant=auth.tenant, authorization=auth, actor=actor, operation="smax_ad_overview",
        parameters={**params, "lastStartDate": "2026-08-30", "lastEndDate": "2026-08-31"},
        status="succeeded", response_hash="a" * 64,
        response={"success": True, "code": "0", "result": {"reportOverviewDetailDTO": {
            "spend": str(sum(map(Decimal, amounts))), "revenue": "81.20", "clicks": 4,
        }}},
    )
    daily = LazadaApiSnapshot.objects.create(
        tenant=auth.tenant, authorization=auth, actor=actor, operation="smax_ad_metrics",
        parameters={**params, "metricType": 1}, status="succeeded", response_hash="b" * 64,
        response={"success": True, "code": "0", "result": {
            "dateList": ["1788192000000", "1788278400000"], "metricList": list(amounts), "hourList": [],
        }},
    )
    return overview, daily


def test_pair_is_idempotent_and_uses_site_dates(context):
    actor, auth = context
    overview, daily = pair(actor, auth)
    result = import_report_pair(actor=actor, overview=overview, daily=daily)
    assert result["daily_sum"] == "15.30"
    assert result["days"] == 2
    import_report_pair(actor=actor, overview=overview, daily=daily)
    assert LazadaAdvertisingDailySpend.objects.count() == 2
    assert list(LazadaAdvertisingDailySpend.objects.order_by("report_date").values_list("report_date__day", flat=True)) == [1, 2]
    assert sum(LazadaAdvertisingDailySpend.objects.values_list("spend", flat=True)) == Decimal("15.30")


@pytest.mark.parametrize("defect", ["missing_day", "duplicate_day", "negative", "nan", "fraction", "mismatch", "failed", "out_of_range", "wrong_metric", "wrong_period", "bool", "nested_failure"])
def test_invalid_response_never_partially_imports(context, defect):
    actor, auth = context
    overview, daily = pair(actor, auth)
    daily.response = deepcopy(daily.response)
    body = daily.response["result"]
    if defect == "missing_day": body["metricList"].pop()
    if defect == "duplicate_day": body["dateList"][1] = body["dateList"][0]
    if defect == "negative": body["metricList"][0] = "-1"
    if defect == "nan": body["metricList"][0] = "NaN"
    if defect == "fraction": body["metricList"][0] = "12.100001"
    if defect == "mismatch": body["metricList"][0] = "0"
    if defect == "failed": daily.status = "failed"
    if defect == "out_of_range": body["dateList"][0] = "1788019200000"
    if defect == "wrong_metric": daily.parameters["metricType"] = 2
    if defect == "wrong_period": daily.parameters["endDate"] = "2026-09-03"
    if defect == "bool": body["metricList"][0] = True
    if defect == "nested_failure": body["success"] = False
    with pytest.raises(ValidationError):
        import_report_pair(actor=actor, overview=overview, daily=daily)
    assert not LazadaAdvertisingDailySpend.objects.exists()


def test_latest_capture_wins_and_native_finance_not_created(context):
    actor, auth = context
    old = pair(actor, auth)
    new = pair(actor, auth, ("15", "5"))
    import_report_pair(actor=actor, overview=new[0], daily=new[1])
    import_report_pair(actor=actor, overview=old[0], daily=old[1])
    assert sum(LazadaAdvertisingDailySpend.objects.values_list("spend", flat=True)) == Decimal("20")
    from apps.finance.models import PlatformFinanceTransaction
    assert not PlatformFinanceTransaction.objects.exists()


def test_scope_denial_happens_before_network(context, monkeypatch):
    actor, auth = context
    client = Mock()
    monkeypatch.setattr("apps.integrations.lazada_api_service.LazadaReadonlyClient", client)
    monkeypatch.setattr("apps.integrations.lazada_api_service.check_user_permission", lambda *a, **k: False)
    with pytest.raises(PermissionDenied):
        sync_advertising(actor=actor, authorization_id=auth.pk, payload={"startDate": "2026-09-01", "endDate": "2026-09-02"})
    client.assert_not_called()


def test_sync_reuses_original_token_and_only_reads_report_paths(context, monkeypatch):
    actor, auth = context
    overview, daily = pair(actor, auth)
    original = (auth.token_id, auth.expires_at, auth.refreshed_at)
    client = Mock()
    client._request.side_effect = [overview.response, daily.response]
    monkeypatch.setattr("apps.integrations.lazada_api_service.LazadaReadonlyClient", lambda *a, **k: client)
    result = sync_advertising(actor=actor, authorization_id=auth.pk, payload={"startDate": "2026-09-01", "endDate": "2026-09-02"})
    assert result["status"] == "succeeded"
    assert [c.args[0] for c in client._request.call_args_list] == [
        "/rest/sponsor/solution/smax/report/getReportOverview",
        "/rest/sponsor/solution/smax/report/getReportOverviewMetric",
    ]
    auth.refresh_from_db()
    assert (auth.token_id, auth.expires_at, auth.refreshed_at) == original


def test_expired_token_is_not_refreshed(context, monkeypatch):
    actor, auth = context
    from apps.integrations.models import authorization_service_write
    with authorization_service_write():
        auth.expires_at = timezone.now() - timedelta(seconds=1)
        auth.save(update_fields=["expires_at"])
    client = Mock()
    monkeypatch.setattr("apps.integrations.lazada_api_service.LazadaReadonlyClient", client)
    with pytest.raises(ValidationError):
        sync_advertising(actor=actor, authorization_id=auth.pk, payload={"startDate": "2026-09-01", "endDate": "2026-09-02"})
    client.assert_not_called()


def test_report_queries_persisted_rows_only(context, monkeypatch):
    actor, auth = context
    overview, daily = pair(actor, auth)
    import_report_pair(actor=actor, overview=overview, daily=daily)
    client = APIClient()
    client.force_authenticate(actor)
    network = Mock(side_effect=AssertionError("Report GET must not call platform"))
    monkeypatch.setattr("apps.integrations.readonly_clients.LazadaReadonlyClient._request", network)
    response = client.get("/api/internal/analytics/advertising/", {
        "platform": "lazada", "period_start": "2026-09-01", "period_end": "2026-09-02",
    })
    assert response.status_code == 200
    assert response.data["data"]["count"] == 2
    assert response.data["data"]["summaries"][0]["spend"] == "15.3000"
    assert response.data["data"]["results"][0]["source_snapshot_id"] == daily.pk
    network.assert_not_called()


def test_foreign_tenant_cannot_import_pair(context):
    actor, auth = context
    overview, daily = pair(actor, auth)
    from apps.tenants.models import Tenant
    from apps.accounts.models import CustomUser
    other = Tenant.objects.create(name="Other", code="other-ads")
    foreign_actor = CustomUser.objects.create_user(username="other-ads", tenant=other, user_type="internal", is_superuser=True)
    with pytest.raises(PermissionDenied):
        import_report_pair(actor=foreign_actor, overview=overview, daily=daily)


@pytest.mark.parametrize("payload", [{"startDate": "2026-09-01", "endDate": "2026-10-02"},
    {"startDate": "2026-09-02", "endDate": "2026-09-01"},
    {"startDate": "2026-09-01", "endDate": "2026-09-02", "access_token": "synthetic"}])
def test_bad_sync_parameters_fail_before_network(context, payload, monkeypatch):
    actor, auth = context
    network = Mock()
    monkeypatch.setattr("apps.integrations.lazada_api_service.LazadaReadonlyClient", network)
    with pytest.raises(ValidationError):
        sync_advertising(actor=actor, authorization_id=auth.pk, payload=payload)
    network.assert_not_called()


def test_report_respects_analytics_scope_in_rows_summaries_and_sync_options(context, monkeypatch):
    actor, auth = context
    overview, daily = pair(actor, auth)
    import_report_pair(actor=actor, overview=overview, daily=daily)
    monkeypatch.setattr("apps.permissions.ui_p6_scopes.analytics_dimension_configs", lambda *a, **k: [{"store_id": auth.store_id + 999}])
    client = APIClient(); client.force_authenticate(actor)
    response = client.get("/api/internal/analytics/advertising/", {
        "platform": "lazada", "period_start": "2026-09-01", "period_end": "2026-09-02"})
    assert response.status_code == 200
    data = response.data["data"]
    assert data["count"] == 0
    assert data["stores"] == data["summaries"] == []


def test_partial_period_does_not_present_overview_as_full_period(context):
    actor, auth = context
    overview, daily = pair(actor, auth)
    import_report_pair(actor=actor, overview=overview, daily=daily)
    client = APIClient(); client.force_authenticate(actor)
    response = client.get("/api/internal/analytics/advertising/", {
        "platform": "lazada", "period_start": "2026-09-01", "period_end": "2026-09-03"})
    summary = response.data["data"]["summaries"][0]
    assert summary["complete"] is False
    assert summary["days"] == 2 and summary["expected_days"] == 3
    assert summary["overview_metrics"] == {}


def test_report_requires_login_and_rejects_unknown_parameters(context):
    actor, _ = context
    client = APIClient()
    assert client.get("/api/internal/analytics/advertising/", {"platform": "lazada"}).status_code in (401, 403)
    client.force_authenticate(actor)
    assert client.get("/api/internal/analytics/advertising/", {"platform": "lazada", "access_token": "synthetic"}).status_code == 400


def test_sync_http_entry_is_available_but_cannot_select_arbitrary_paths(context, monkeypatch):
    actor, auth = context
    overview, daily = pair(actor, auth)
    client = Mock(); client._request.side_effect = [overview.response, daily.response]
    monkeypatch.setattr("apps.integrations.lazada_api_service.LazadaReadonlyClient", lambda *a, **k: client)
    api = APIClient(); api.force_authenticate(actor)
    response = api.post(f"/api/internal/integrations/lazada-authorizations/{auth.pk}/operations/", {
        "operation": "smax_sync", "payload": {"startDate": "2026-09-01", "endDate": "2026-09-02"}}, format="json")
    assert response.status_code == 200 and response.data["data"]["status"] == "succeeded"
    response = api.post(f"/api/internal/integrations/lazada-authorizations/{auth.pk}/operations/", {
        "operation": "smax_sync", "payload": {"startDate": "2026-09-01", "endDate": "2026-09-02", "path": "/refresh"}}, format="json")
    assert response.status_code == 400
    assert client._request.call_count == 2
