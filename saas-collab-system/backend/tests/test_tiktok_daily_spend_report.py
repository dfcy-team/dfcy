from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import AdsOAuthSession, PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend
from apps.integrations.oauth_state_service import configuration_digest
from django.utils import timezone
from datetime import timedelta
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db
URL = "/api/internal/analytics/advertising/tiktok-daily-spend/"


@pytest.fixture
def setup_report():
    tenant = Tenant.objects.create(code="report", name="Report")
    user = CustomUser.objects.create_user(username="report", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TK", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="TK1", name="TK", country_code="PH")
    config = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="tiktok", account_alias="ads",
        environment="pilot", created_by=user, platform_config={"api_type": "advertising"})
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
        advertiser_id="100", token_id="tok_" + "1" * 32, currency="PHP", timezone="Asia/Manila", enabled=False)
    roles = {}
    for code in ("analytics.view", "integrations.store.view"):
        role = Role.objects.create(tenant=tenant, code=code, name=code)
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code,
            "module": code.split(".")[0], "action": "view", "permission_type": "action"})
        role.permissions.add(permission)
        UserRole.objects.create(tenant=tenant, user=user, role=role)
        roles[code] = DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    client = APIClient()
    client.force_authenticate(user)
    return client, user, mapping, roles


def get(client, **params):
    return client.get(URL, {"date_from": "2026-10-01", "date_to": "2026-10-02", **params})


def fact(mapping, date="2026-10-01", spend="0", currency="PHP"):
    return TikTokAdsDailySpend.objects.create(tenant=mapping.tenant, mapping=mapping, date=date, spend=spend, currency=currency)


def test_unknown_zero_partial_disabled_and_read_only(setup_report):
    client, _, mapping, _ = setup_report
    empty = get(client).data["data"]["totals"][0]
    assert empty["currency"] == "PHP"
    assert empty["total"] is None and empty["known_subtotal"] is None
    assert empty["expected_days"] == 2 and empty["stored_days"] == 0
    fact(mapping)
    with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")), \
         patch("apps.integrations.custody.get_custody_backend", side_effect=AssertionError("custody forbidden")), \
         CaptureQueriesContext(connection) as captured:
        response = get(client)
    assert response.status_code == 200
    data = response.data["data"]
    assert data["coverage"] == {"visible_mappings": 1, "mapping_days": 2, "stored": 1, "missing": 1, "explicit_zero": 1}
    assert data["totals"][0]["total"] is None
    assert data["results"][0]["spend"] == "0.000000"
    assert "tok_" not in str(data)
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in captured)


def test_exact_currency_totals_across_pages(setup_report):
    client, _, mapping, _ = setup_report
    fact(mapping, spend="1234.123456")
    fact(mapping, date="2026-10-02", spend="0.000001", currency="USD")
    data = get(client, page_size=1, page=2).data["data"]
    assert len(data["results"]) == 1
    assert {t["currency"]: t["known_subtotal"] for t in data["totals"]} == {"PHP": "1234.123456", "USD": "0.000001"}
    assert all(t["total"] is None for t in data["totals"])
    assert "fact_currency_differs_from_current_mapping" in data["warnings"]
    assert data["totals"][0]["missing_days"] == 1


def test_same_currency_subtotal_spans_pages(setup_report):
    client, _, mapping, _ = setup_report
    fact(mapping, spend="0.100001")
    fact(mapping, date="2026-10-02", spend="0.200002")
    data = get(client, page_size=1).data["data"]
    assert data["totals"][0]["total"] == "0.300003"
    assert data["totals"][0]["expected_days"] == 2
    assert data["totals"][0]["missing_days"] == 0
    assert len(data["results"]) == 1


@pytest.mark.parametrize("params", [{"date_from": ""}, {"date_to": "2026-11-01"},
    {"date_to": "2026-09-30"}, {"page": 0}, {"page_size": 101}, {"page_size": 0}, {"advertiser_id": "bad"},
    {"platform": "shopee"}])
def test_query_validation(setup_report, params):
    assert get(setup_report[0], **params).status_code == 400


@pytest.mark.parametrize("code,config", [
    ("analytics.view", {"analytics_dimensions": [{"store_id": "99999"}]}),
    ("analytics.view", {"analytics_dimensions": [{"sku_id": 1}]}),
    ("integrations.store.view", {"store_ids": [99999]}),
])
def test_scope_intersection_and_hidden_ids(setup_report, code, config):
    client, _, mapping, roles = setup_report
    scope = roles[code]
    scope.scope_type, scope.config = "custom", config
    scope.save()
    assert get(client).data["data"]["coverage"]["visible_mappings"] == 0
    assert get(client, store_id=mapping.store_id).status_code == 404
    assert get(client, advertiser_id=mapping.advertiser_id).status_code == 404
    assert get(client).data["data"]["subjects"] == []


@pytest.mark.parametrize("target", ["fact", "mapping", "store", "platform", "config"])
def test_inconsistent_tenant_foreign_keys(setup_report, target):
    client, _, mapping, _ = setup_report
    row = fact(mapping)
    other = Tenant.objects.create(code="other", name="Other")
    obj = {"fact": row, "mapping": mapping, "store": mapping.store,
        "platform": mapping.store.platform, "config": mapping.integration_config}[target]
    type(obj).objects.filter(pk=obj.pk).update(tenant=other)
    assert get(client).data["data"]["results"] == []


@pytest.mark.parametrize("code", ["analytics.view", "integrations.store.view"])
def test_requires_both_actions(setup_report, code):
    client, _, _, roles = setup_report
    roles[code].role.permissions.clear()
    assert get(client).status_code == 403


def test_inactive_tenant_and_user(setup_report):
    client, user, _, _ = setup_report
    user.tenant.status = "suspended"
    user.tenant.save()
    assert get(client).status_code == 403


def test_explicit_dates_and_page_boundaries(setup_report):
    client, _, mapping, _ = setup_report
    assert client.get(URL).status_code == 400
    assert get(client, page=2).status_code == 404
    fact(mapping)
    assert get(client, page=2).status_code == 404
    assert get(client, date_to="2026-10-31", page_size=100).status_code == 200


def test_positive_scope_intersection(setup_report):
    client, _, mapping, roles = setup_report
    configs = {"analytics.view": {"analytics_dimensions": [{"platform": "tiktok", "store_id": str(mapping.store_id), "country": "PH"}]},
               "integrations.store.view": {"platforms": ["tiktok"], "store_ids": [mapping.store_id], "resource_types": ["advertising_report"]}}
    for code, config in configs.items():
        scope = roles[code]
        scope.scope_type, scope.config = "custom", config
        scope.save()
    fact(mapping)
    assert get(client).data["data"]["count"] == 1


def test_inactive_user_and_noninternal_are_denied(setup_report):
    client, user, _, _ = setup_report
    user.is_active = False
    assert get(client).status_code == 403
    user.is_active = True
    user.user_type = "external"
    assert get(client).status_code == 403


def test_complete_php_is_not_suppressed_by_missing_usd(setup_report):
    client, _, mapping, _ = setup_report
    TikTokAdsAdvertiserMapping.objects.create(tenant=mapping.tenant, store=mapping.store,
        integration_config=mapping.integration_config, advertiser_id="200", token_id="tok_" + "2" * 32,
        currency="USD", timezone="Asia/Manila")
    fact(mapping, spend="1.000001")
    fact(mapping, date="2026-10-02", spend="2.000002")
    data = get(client, page_size=1).data["data"]
    php, usd = data["totals"]
    assert php["currency"] == "PHP" and php["total"] == "3.000003" and php["complete"]
    assert usd["currency"] == "USD" and usd["expected_days"] == 2 and usd["missing_days"] == 2
    assert usd["total"] is None and usd["known_subtotal"] is None
    assert len(data["subjects"]) == 2


def test_local_bound_evidence_expiry_and_disabled_do_not_gate_history(setup_report):
    client, user, mapping, _ = setup_report
    fact(mapping)
    session = AdsOAuthSession.objects.create(tenant=user.tenant, store=mapping.store,
        integration_config=mapping.integration_config, actor=user, state_hash="report-evidence",
        config_fingerprint=configuration_digest(mapping.integration_config),
        expires_at=timezone.now() - timedelta(days=1), status="bound", token_id=mapping.token_id,
        credential_id="private-custody-ref", candidates=[{"advertiser_id": mapping.advertiser_id,
            "verify_state": "verified", "verified_at": "2026-10-01T00:00:00Z", "currency": "PHP", "timezone": "Asia/Manila"}],
        binding_results=[{"mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id}])
    data = get(client).data["data"]
    assert data["count"] == 1 and data["subjects"][0]["local_evidence"] == "verified"
    assert data["subjects"][0]["collection_enabled"] is False
    assert "collection_disabled" in data["warnings"]
    assert "private-custody-ref" not in str(data) and "tok_" not in str(data)
    session.config_fingerprint = "stale"
    session.save(update_fields=["config_fingerprint"])
    data = get(client).data["data"]
    assert data["count"] == 1 and data["subjects"][0]["local_evidence"] == "unverified"
