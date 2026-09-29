from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone as django_timezone

from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant
from apps.integrations.models import (
    PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend, TikTokAdsSyncLease,
)
from apps.integrations import tiktok_ads_pilot as pilot


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttp:
    def __init__(self, *, missing=False, malformed=False, paginated=False, duplicate=False,
                 incomplete=False, zero=False, hook=None, hook_after_reports=1, malformed_advertiser_id=None):
        self.calls = []
        self.missing = missing
        self.malformed = malformed
        self.paginated = paginated
        self.duplicate = duplicate
        self.incomplete = incomplete
        self.zero = zero
        self.hook = hook
        self.hook_after_reports = hook_after_reports
        self.report_count = 0
        self.malformed_advertiser_id = malformed_advertiser_id

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        query = parse_qs(urlparse(url).query)
        if urlparse(url).path == pilot.INFO_PATH:
            advertiser_id = query["advertiser_ids"][0].strip('["]')
            return FakeResponse({"code": 0, "data": {"list": [{
                "advertiser_id": advertiser_id, "currency": "USD", "timezone": "UTC",
            }]}})
        self.report_count += 1
        if self.hook and self.report_count >= self.hook_after_reports:
            hook, self.hook = self.hook, None
            hook()
        assert query["start_date"] == query["end_date"]
        assert query["service_type"] == ["AUCTION"]
        assert query["data_level"] == ["AUCTION_CAMPAIGN"]
        assert query["dimensions"] == ['["campaign_id"]']
        assert query["metrics"] == ['["spend"]']
        day = query["start_date"][0]
        page = int(query["page"][0])
        if self.missing and day == "2026-09-28":
            return FakeResponse({"code": 0, "data": {"page_info": {"total_page": 0}, "list": []}})
        if self.paginated and page == 2:
            row = {"dimensions": {"campaign_id": "1" if self.duplicate else "2"},
                   "metrics": {"spend": "2.000001"}}
            rows = [] if self.incomplete else [row]
        else:
            rows = [{"dimensions": {"campaign_id": "1"},
                     "metrics": {"spend": "not-a-number" if self.malformed and (
                         self.malformed_advertiser_id is None or
                         query["advertiser_id"][0] == self.malformed_advertiser_id
                     ) else "0" if self.zero else "1.123456"}}]
        return FakeResponse({"code": 0, "data": {
            "page_info": {"total_page": 2 if self.paginated else 1}, "list": rows,
        }})


class FakeCustody:
    def retrieve_access_token(self, token_id):
        assert token_id.startswith("tok_")
        return "synthetic-secret"


@pytest.fixture
def two_stores(db, monkeypatch):
    monkeypatch.setattr(pilot, "require_live_mode", lambda _: None)
    tenant = Tenant.objects.create(id=1, code="tenant-1", name="Pilot")
    user = get_user_model().objects.create_user(
        username="ads-pilot-operator", tenant=tenant, user_type="internal", is_superuser=True,
    )
    platform = PlatformMaster.objects.create(tenant=tenant, code="tiktok", name="TikTok", platform_type="tiktok")
    stores = []
    for n, (code, count) in enumerate(pilot.PILOT_ACCOUNT_COUNTS.items(), start=1):
        config = PlatformIntegrationConfig.objects.create(
            tenant=tenant, platform="tiktok", account_alias=f"ads-pilot-{code}", created_by=user,
            environment=PlatformIntegrationConfig.Environment.PILOT,
            status=PlatformIntegrationConfig.Status.VERIFIED,
            platform_config={"api_type": "advertising"},
            network_enabled=True, sync_read_enabled=True, sync_write_enabled=False,
        )
        store = StoreMaster.objects.create(
            tenant=tenant, platform=platform, code=code, name=f"Shop {n}",
            country_code="US", currency="USD", timezone="UTC",
        )
        for index in range(count):
            TikTokAdsAdvertiserMapping.objects.create(
                tenant=tenant, store=store, integration_config=config,
                advertiser_id=str(n * 100 + index), token_id=f"tok_{n:032x}",
                currency="USD", timezone="UTC", enabled=True,
            )
        stores.append(store)
    return tenant, stores


@pytest.mark.django_db
def test_two_shop_upsert_and_original_currency(two_stores):
    tenant, stores = two_stores
    http = FakeHttp()
    kwargs = dict(tenant_id=tenant.id, approved_store_ids=[s.id for s in stores],
                  now=datetime(2026, 9, 29, tzinfo=timezone.utc), http=http, custody=FakeCustody())
    first = pilot.sync_seven_complete_days(**kwargs)
    second = pilot.sync_seven_complete_days(**kwargs)
    assert len(first) == len(second) == 12
    assert all(item["spend_scope"] == "AUCTION_CAMPAIGN" for item in first)
    assert all(item["days_written"] == 7 and not item["missing_days"] for item in first)
    assert TikTokAdsDailySpend.objects.filter(tenant=tenant).count() == 84
    assert set(TikTokAdsDailySpend.objects.values_list("spend", "currency")) == {(Decimal("1.123456"), "USD")}
    report_calls = [call for call in http.calls if urlparse(call[1]).path == pilot.REPORT_PATH]
    assert len(report_calls) == 168
    assert all(call[0] == "GET" and call[2]["headers"] == {"Access-Token": "synthetic-secret"}
               and "synthetic-secret" not in call[1] for call in http.calls)


@pytest.mark.django_db
def test_scope_and_tenant_guard_before_network(two_stores):
    tenant, stores = two_stores
    http = FakeHttp()
    other = Tenant.objects.create(code="pilot-b", name="Pilot B")
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(tenant_id=other.id, approved_store_ids=[s.id for s in stores], http=http)
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(tenant_id=tenant.id, approved_store_ids=[stores[0].id], http=http)
    assert not http.calls
    mapping = TikTokAdsAdvertiserMapping.objects.first()
    mapping.tenant = other
    with pytest.raises(ValidationError):
        mapping.save()


@pytest.mark.django_db
def test_missing_day_is_not_zero_and_malformed_report_does_not_write(two_stores):
    tenant, stores = two_stores
    kwargs = dict(tenant_id=tenant.id, approved_store_ids=[s.id for s in stores],
                  now=datetime(2026, 9, 29, tzinfo=timezone.utc), custody=FakeCustody())
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(http=FakeHttp(malformed=True), **kwargs)
    assert TikTokAdsDailySpend.objects.count() == 0
    result = pilot.sync_seven_complete_days(http=FakeHttp(missing=True), **kwargs)
    assert all(item["days_written"] == 6 and item["missing_days"] == ["2026-09-28"] for item in result)
    assert TikTokAdsDailySpend.objects.count() == 72
    previous = pilot.sync_seven_complete_days(http=FakeHttp(), **kwargs)
    assert all(item["days_written"] == 7 for item in previous)
    TikTokAdsDailySpend.objects.filter(date="2026-09-28").update(spend=Decimal("99.000000"))
    pilot.sync_seven_complete_days(http=FakeHttp(missing=True), **kwargs)
    assert set(TikTokAdsDailySpend.objects.filter(date="2026-09-28").values_list("spend", flat=True)) == {Decimal("99")}
    zero_result = pilot.sync_seven_complete_days(http=FakeHttp(zero=True), **kwargs)
    assert all(item["days_written"] == 7 and not item["missing_days"] for item in zero_result)
    assert set(TikTokAdsDailySpend.objects.filter(date="2026-09-28").values_list("spend", flat=True)) == {Decimal("0")}


@pytest.mark.django_db
def test_campaign_pages_are_summed_once_and_incomplete_pages_abort(two_stores):
    tenant, stores = two_stores
    kwargs = dict(tenant_id=tenant.id, approved_store_ids=[s.id for s in stores],
                  now=datetime(2026, 9, 29, tzinfo=timezone.utc), custody=FakeCustody())
    for http in (FakeHttp(paginated=True, duplicate=True), FakeHttp(paginated=True, incomplete=True)):
        with pytest.raises(ValidationError):
            pilot.sync_seven_complete_days(http=http, **kwargs)
        assert TikTokAdsDailySpend.objects.count() == 0
    http = FakeHttp(paginated=True)
    result = pilot.sync_seven_complete_days(http=http, **kwargs)
    assert all(item["days_written"] == 7 for item in result)
    assert set(TikTokAdsDailySpend.objects.values_list("spend", flat=True)) == {Decimal("3.123457")}
    assert len([call for call in http.calls if urlparse(call[1]).path == pilot.REPORT_PATH]) == 168


@pytest.mark.django_db
def test_one_store_can_have_many_advertisers_but_not_raw_tokens(two_stores):
    tenant, stores = two_stores
    config = TikTokAdsAdvertiserMapping.objects.first().integration_config
    with pytest.raises(ValidationError):
        TikTokAdsAdvertiserMapping.objects.create(
            tenant=tenant, store=stores[0], integration_config=config, advertiser_id="999",
            token_id="raw-access-token", currency="USD", timezone="UTC", enabled=True,
        )
    assert TikTokAdsAdvertiserMapping.objects.filter(store=stores[0]).count() == 2
    result = pilot.sync_seven_complete_days(
        tenant_id=tenant.id, approved_store_ids=[s.id for s in stores],
        now=datetime(2026, 9, 29, tzinfo=timezone.utc), http=FakeHttp(), custody=FakeCustody(),
    )
    assert len(result) == 12
    assert TikTokAdsDailySpend.objects.count() == 84


@pytest.mark.django_db
def test_ads_config_isolation_and_read_only_approval(two_stores):
    tenant, stores = two_stores
    mapping = TikTokAdsAdvertiserMapping.objects.first()
    config = mapping.integration_config
    original = (config.platform, config.platform_config, config.environment, config.sync_write_enabled)
    for field, invalid in (
        ("platform", "shopee"),
        ("platform_config", {"api_type": "marketplace"}),
        ("environment", config.Environment.MOCK),
        ("sync_write_enabled", True),
    ):
        setattr(config, field, invalid)
        with pytest.raises(ValidationError):
            mapping.full_clean()
        config.platform, config.platform_config, config.environment, config.sync_write_enabled = original
    other = Tenant.objects.create(code="pilot-other", name="Other")
    config.tenant = other
    with pytest.raises(ValidationError):
        mapping.full_clean()
    config.tenant = tenant
    config.status = config.Status.DISABLED
    config.save(update_fields=["status"])
    http = FakeHttp()
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(tenant_id=tenant.id, approved_store_ids=[s.id for s in stores], http=http)
    assert not http.calls


def test_campaign_page_metadata_must_be_consistent_and_bounded():
    row = {"dimensions": {"campaign_id": "1"}, "metrics": {"spend": "1.25"}}
    with pytest.raises(ValidationError):
        pilot._parse_campaign_page({"page_info": {"total_page": 3}, "list": [row]}, 2, 2)
    with pytest.raises(ValidationError):
        pilot._parse_campaign_page({"page_info": {"total_page": pilot.MAX_REPORT_PAGES + 1}, "list": [row]}, 1, None)
    with pytest.raises(ValidationError):
        pilot._parse_campaign_page({"page_info": {"total_page": 0}, "list": [row]}, 1, None)
    assert pilot._parse_campaign_page({"page_info": {"total_page": 0}}, 1, None) == (0, {})


def test_real_zero_campaign_rows_are_not_empty_pages():
    mapping = SimpleNamespace(advertiser_id="101")
    token = "test-synthetic-secret"
    day = datetime(2026, 9, 28, tzinfo=timezone.utc).date()
    assert pilot._campaign_spend_for_day(FakeHttp(zero=True), mapping, token, day) == Decimal("0")
    assert pilot._campaign_spend_for_day(FakeHttp(missing=True), mapping, token, day) is None


@pytest.mark.django_db
def test_exact_approved_account_set_required_before_network(two_stores):
    tenant, stores = two_stores
    args = dict(tenant_id=tenant.pk, approved_store_ids=[store.pk for store in stores],
                now=datetime(2026, 9, 29, tzinfo=timezone.utc), custody=FakeCustody())
    http = FakeHttp()
    missing = TikTokAdsAdvertiserMapping.objects.get(advertiser_id="100")
    missing.enabled = False
    missing.save(update_fields=["enabled", "updated_at"])
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(http=http, **args)
    missing.enabled = True
    missing.save(update_fields=["enabled", "updated_at"])
    extra = TikTokAdsAdvertiserMapping.objects.create(
        tenant=tenant, store=stores[0], integration_config=missing.integration_config,
        advertiser_id="999", token_id=missing.token_id, currency="USD", timezone="UTC", enabled=False,
    )
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(http=http, **args)
    extra.delete()
    stores[0].code = "OTHER"
    stores[0].save(update_fields=["code"])
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(http=http, **args)
    stores[0].code = "TK1PH"
    stores[0].save(update_fields=["code"])
    missing.delete()
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(http=http, **args)
    assert not http.calls
    assert TikTokAdsDailySpend.objects.count() == 0


@pytest.mark.django_db
def test_disable_during_network_aborts_without_partial_dates(two_stores):
    tenant, stores = two_stores
    mapping = TikTokAdsAdvertiserMapping.objects.get(advertiser_id="209")

    def disable():
        TikTokAdsAdvertiserMapping.objects.filter(pk=mapping.pk).update(enabled=False)

    http = FakeHttp(hook=disable, hook_after_reports=8)
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(
            tenant_id=tenant.pk, approved_store_ids=[s.pk for s in stores],
            now=datetime(2026, 9, 29, tzinfo=timezone.utc), http=http, custody=FakeCustody(),
        )
    assert http.report_count == 8
    assert TikTokAdsDailySpend.objects.count() == 0
    assert TikTokAdsSyncLease.objects.get(tenant=tenant).owner_token == ""


@pytest.mark.django_db
def test_active_lease_rejects_second_run_and_expired_owner_cannot_overwrite(two_stores):
    tenant, stores = two_stores
    args = dict(tenant_id=tenant.pk, approved_store_ids=[s.pk for s in stores],
                now=datetime(2026, 9, 29, tzinfo=timezone.utc), custody=FakeCustody())

    def reject_overlap():
        with pytest.raises(ValidationError, match="active sync lease"):
            pilot.sync_seven_complete_days(http=FakeHttp(), **args)

    pilot.sync_seven_complete_days(http=FakeHttp(hook=reject_overlap), **args)
    assert TikTokAdsDailySpend.objects.count() == 84

    def take_over():
        TikTokAdsSyncLease.objects.filter(tenant=tenant).update(
            lease_expires_at=django_timezone.now() - timedelta(seconds=1),
        )
        pilot.sync_seven_complete_days(http=FakeHttp(zero=True), **args)

    with pytest.raises(ValidationError, match="ownership was lost"):
        pilot.sync_seven_complete_days(http=FakeHttp(hook=take_over), **args)
    assert TikTokAdsDailySpend.objects.count() == 84
    assert set(TikTokAdsDailySpend.objects.values_list("spend", flat=True)) == {Decimal("0")}


@pytest.mark.django_db
def test_late_report_failure_never_writes_partial_dates(two_stores):
    tenant, stores = two_stores
    with pytest.raises(ValidationError):
        pilot.sync_seven_complete_days(
            tenant_id=tenant.pk, approved_store_ids=[s.pk for s in stores],
            now=datetime(2026, 9, 29, tzinfo=timezone.utc),
            http=FakeHttp(malformed=True, malformed_advertiser_id="209"), custody=FakeCustody(),
        )
    assert TikTokAdsDailySpend.objects.count() == 0
