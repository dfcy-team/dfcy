"""Database-backed regressions for the stored GMV Max campaign read path."""
from datetime import date
from types import SimpleNamespace

import pytest

from apps.integrations.gmv_max_campaigns import campaign_report
from apps.integrations.gmv_max_read import stored_days
from apps.integrations.gmv_max_sync import PAGE_SIZE, REPORT_PATH
from apps.integrations.models import IntegrationAuditLog, SharedAdvertisingRawPayload
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.accounts.models import CustomUser
from apps.integrations.models import PlatformIntegrationConfig
from apps.tenants.models import Tenant
from tests.test_tiktok_daily_spend_report import setup_report as shared_setup_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def campaign_scope():
    tenant = Tenant.objects.create(code="campaign-read", name="Campaign read")
    user = CustomUser.objects.create_user(username="campaign-read", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="campaign-tk", name="TikTok",
        platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="TK-CAMPAIGN",
        name="Campaign store", country_code="PH")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="tiktok",
        account_alias="campaign ads", environment="pilot", created_by=user,
        platform_config={"api_type": "advertising"})
    mapping = SimpleNamespace(pk=1, store_id=store.pk, store=store, advertiser_id="100",
        integration_config_id=config.pk, currency="USD", timezone="Asia/Manila")
    return user, tenant, store, config, mapping


def save_snapshot(tenant, store, date_value, cost, *, platform_store_id="200", currency="USD",
                  timezone="Asia/Manila", campaign_id="300", payload_tenant=None):
    payload = {"schema": "gmv-max-day-v1", "advertiser_id": "100", "date": date_value,
        "platform_store_id": platform_store_id, "currency": currency, "timezone": timezone,
        "report_scope": "GMV_MAX_CAMPAIGN", "store_evidence": {
            "store_id": platform_store_id, "is_gmv_max_available": True,
            "exclusive_authorized_advertiser_info": {"advertiser_id": "100"}},
        "pages": [{"page_info": {"page": 1, "page_size": PAGE_SIZE, "total_page": 1,
            "total_number": 1}, "list": [{"dimensions": {"campaign_id": campaign_id},
            "metrics": {"cost": cost, "gross_revenue": "50", "orders": "2"}}]}]}
    return SharedAdvertisingRawPayload.objects.create(tenant=payload_tenant or tenant, store=store,
        platform="tiktok", endpoint=REPORT_PATH, payload_hash=(cost + currency + timezone + platform_store_id).encode().hex().ljust(64, "0")[:64], payload=payload)


def audit(tenant, config, user, raw):
    return IntegrationAuditLog.objects.create(tenant=tenant, integration_config=config, actor=user,
        action="ads_gmv_max_day", result="success", masked_detail={"raw_payload_id": raw.pk})


def test_real_raw_a_b_a_uses_latest_audit_and_campaign_projection(campaign_scope):
    user, tenant, store, config, mapping = campaign_scope
    a = save_snapshot(tenant, store, "2026-11-01", "10")
    b = save_snapshot(tenant, store, "2026-11-01", "12", campaign_id="301")
    audit(tenant, config, user, a)
    audit(tenant, config, user, b)
    latest = audit(tenant, config, user, a)

    rows = stored_days(user, [mapping], {}, date(2026, 11, 1), date(2026, 11, 1), include_campaigns=True)
    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == a.pk
    assert rows[0]["fetched_at"] == latest.created_at.isoformat()
    assert rows[0]["campaigns"] == [{"campaign_id": "300", "cost": "10",
        "gross_revenue": "50", "orders": "2"}]


def test_raw_scope_separates_currency_timezone_and_tenant(campaign_scope):
    user, tenant, store, _config, mapping = campaign_scope
    other_tenant = Tenant.objects.create(code="campaign-other", name="Other tenant")
    usd_manila = save_snapshot(tenant, store, "2026-11-01", "10")
    save_snapshot(tenant, store, "2026-11-01", "11", currency="PHP")
    save_snapshot(tenant, store, "2026-11-01", "12", timezone="Asia/Bangkok")
    save_snapshot(tenant, store, "2026-11-01", "99", payload_tenant=other_tenant)

    rows = stored_days(user, [mapping], {}, date(2026, 11, 1), date(2026, 11, 1), include_campaigns=True)
    assert {(r["currency"], r["timezone"], r["cost"]) for r in rows} == {
        ("USD", "Asia/Manila", "10"), ("PHP", "Asia/Manila", "11"),
        ("USD", "Asia/Bangkok", "12")}
    assert usd_manila.pk in {r["snapshot_id"] for r in rows}


def test_no_snapshot_and_verified_empty_campaign_day_do_not_invent_campaign_zero():
    assert campaign_report([], 1) == []
    no_campaigns = {"store_code": "TK1", "advertiser_id": "100", "platform_store_id": "200",
        "currency": "USD", "timezone": "Asia/Manila", "date": "2026-11-01", "campaigns": []}
    assert campaign_report([no_campaigns], 1) == []


def test_campaign_endpoint_requires_visible_store_and_reads_real_snapshot(monkeypatch):
    # Reuse the established local role/store permission fixture, bypassing only
    # pytest's fixture wrapper so this regression stays in the new owned file.
    client, user, mapping, roles = shared_setup_report.__wrapped__()
    url = "/api/internal/analytics/advertising/tiktok-daily-spend/"
    monkeypatch.setattr("apps.reports.tiktok_ads_views.is_module_enabled", lambda _code: True)
    raw = SharedAdvertisingRawPayload.objects.create(tenant=user.tenant, store=mapping.store,
        platform="tiktok", endpoint=REPORT_PATH, payload_hash="c" * 64,
        payload={"schema": "gmv-max-day-v1", "advertiser_id": mapping.advertiser_id,
            "date": "2026-11-01", "platform_store_id": "200", "currency": "PHP",
            "timezone": "Asia/Manila", "pages": [{"page_info": {"page": 1,
                "page_size": PAGE_SIZE, "total_page": 1, "total_number": 1}, "list": [{
                "dimensions": {"campaign_id": "300"}, "metrics": {"cost": "7",
                    "gross_revenue": "20", "orders": "1"}}]}]})
    IntegrationAuditLog.objects.create(tenant=user.tenant, integration_config=mapping.integration_config,
        actor=user, action="ads_gmv_max_day", result="success",
        masked_detail={"raw_payload_id": raw.pk})

    response = client.get(url, {"report_type": "gmv_max_campaigns", "store_id": mapping.store_id,
        "date_from": "2026-11-01", "date_to": "2026-11-01"})
    assert response.status_code == 200
    assert response.data["data"]["campaigns"][0]["campaign_id"] == "300"
    assert response.data["data"]["campaigns"][0]["cost"] == "7"

    StoreMaster.objects.create(tenant=user.tenant, platform=mapping.store.platform,
        code='campaign-assigned-other', name='Assigned other store', country_code='PH', operator=user)
    denied = client.get(url, {"report_type": "gmv_max_campaigns", "store_id": mapping.store_id,
        "date_from": "2026-11-01", "date_to": "2026-11-01"})
    assert denied.status_code == 404
