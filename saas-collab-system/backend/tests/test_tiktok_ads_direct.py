"""Synthetic direct-only callbacks. Main coordinates execution in an isolated DB."""
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core import signing
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations import tiktok_ads_direct as direct, tiktok_ads_oauth as ads
from apps.integrations.models import AdsOAuthSession, PlatformIntegrationConfig, authorization_service_write
from tests.test_lazada_store_authorization import lazada_context

pytestmark = pytest.mark.django_db
CALLBACK = "https://saas.example.test/integrations/tiktok-ads/direct-callback"
VERIFIER = "v" * 64


@pytest.fixture
def flow(lazada_context, settings, monkeypatch):
    _, store, config = lazada_context
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = CALLBACK
    store.platform.platform_type = "tiktok"
    store.platform.save()
    config.platform = "tiktok"
    config.status = "verified"
    config.platform_config = {"api_type": "advertising", "app_id": "123456789"}
    config.callback_url = CALLBACK
    config.network_enabled, config.sync_read_enabled = True, True
    config.credential_status = "configured"
    config.credential_id = "cre_" + "b" * 32
    with authorization_service_write():
        config.save()
    monkeypatch.setattr(ads, "require_live_mode", lambda *a: None)
    monkeypatch.setattr(ads, "get_runtime_platform_config", lambda *a: {"contract_approved": True})
    monkeypatch.setattr(ads, "get_runtime_setting", lambda *a, **k: [CALLBACK])
    monkeypatch.setattr(ads, "integration_values_allowed", lambda *a, **k: True)
    monkeypatch.setattr(ads.PlatformHttpClient, "request", Mock(side_effect=AssertionError("Network denied")))
    backend = Mock()
    backend.retrieve_secret.return_value = "SYNTHETIC_SECRET"
    backend.retrieve_access_token.return_value = "SYNTHETIC_TOKEN"
    backend.store_secrets.return_value = {"credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    monkeypatch.setattr(ads, "custody", lambda: backend)
    actor = config.created_by
    result = ads.start(actor, store.pk, config.pk, VERIFIER)
    session = AdsOAuthSession.objects.get(pk=result["session_id"])
    state = parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    return actor, store, config, session, result, {"state": state, "auth_code": "SYNTHETIC_CODE"}, backend


def finish(flow, **overrides):
    actor, _, _, _, result, params, _ = flow
    values = {"browser_token": result["direct_callback"]["browser_token"],
        "browser_verifier": VERIFIER, "callback_params": params}
    values.update(overrides)
    return direct.complete(actor, **values)


@pytest.mark.parametrize("params", [None, [], {}, {"auth_code": "x"},
    {"state": "wrong", "auth_code": "x"}, {"state": ["x"], "auth_code": "x"}])
def test_hostile_params_do_not_claim(flow, params):
    with pytest.raises(ValidationError):
        finish(flow, callback_params=params)
    flow[3].refresh_from_db()
    assert flow[3].status == "pending" and flow[3].consumed_at is None
    flow[6].retrieve_secret.assert_not_called()


@pytest.mark.parametrize("change", ["nonce", "token", "actor", "tenant", "expiry", "config", "setting", "permission", "callback_app"])
def test_binding_rechecked_before_claim(flow, monkeypatch, settings, change):
    actor, _, config, session, result, params, backend = flow
    values = {}
    if change == "nonce": values["browser_verifier"] = "z" * 64
    elif change == "token": values["browser_token"] = result["direct_callback"]["browser_token"] + "x"
    elif change in {"actor", "tenant"}:
        claims = signing.loads(result["direct_callback"]["browser_token"], salt=direct.SALT)
        claims[change + "_id"] += 100000
        values["browser_token"] = signing.dumps(claims, salt=direct.SALT)
    elif change == "expiry": AdsOAuthSession.objects.filter(pk=session.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif change == "config": PlatformIntegrationConfig.objects.filter(pk=config.pk).update(config_version=999)
    elif change == "setting": settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = ""
    elif change == "permission": monkeypatch.setattr(ads, "integration_values_allowed", lambda *a, **k: False)
    else: values["callback_params"] = {**params, "id": "987654321"}
    with pytest.raises((ValidationError, PermissionDenied, ads.Conflict)):
        finish(flow, **values)
    session.refresh_from_db()
    assert session.consumed_at is None
    backend.retrieve_secret.assert_not_called()


@pytest.mark.parametrize("variant", ["auth_code", "code_only", "both", "different_code"])
def test_official_callback_uses_auth_code_and_checks_optional_app_id(flow, monkeypatch, variant):
    params = {**flow[5], "id": "123456789"}
    if variant == "code_only":
        params["code"] = params.pop("auth_code")
    elif variant in {"both", "different_code"}:
        params["code"] = params["auth_code"] if variant == "both" else "OTHER_OPAQUE_VALUE"
    calls = []

    def request(session, method, url, **kwargs):
        if url.endswith("access_token/"):
            calls.append(kwargs["body"]["auth_code"])
            return {"access_token": "SYNTHETIC_TOKEN"}
        return {"list": []}

    monkeypatch.setattr(ads, "request_json", request)
    assert finish(flow, callback_params=params)["status"] == "authorized"
    assert calls == ["SYNTHETIC_CODE"]
    with pytest.raises(ads.Conflict):
        finish(flow, callback_params=params)
    assert calls == ["SYNTHETIC_CODE"]


@pytest.mark.parametrize("value", ["", "wrong", "1234", "123456780", "1" * 41, 123456789])
def test_bad_optional_app_id_never_claims_or_reads_secret(flow, value):
    with pytest.raises(ValidationError):
        finish(flow, callback_params={**flow[5], "id": value})
    flow[3].refresh_from_db()
    assert flow[3].consumed_at is None
    flow[6].retrieve_secret.assert_not_called()


@pytest.mark.parametrize("timeout", [False, True])
def test_exchange_once_and_sanitized_result(flow, monkeypatch, timeout):
    calls = []
    def request(session, method, url, **kwargs):
        calls.append(url)
        assert url.startswith(ads.HOST)
        if url.endswith("access_token/"):
            if timeout: raise TimeoutError("synthetic")
            return {"access_token": "SYNTHETIC_TOKEN"}
        return {"list": []}
    monkeypatch.setattr(ads, "request_json", request)
    if timeout:
        with pytest.raises(ValidationError): finish(flow)
    else:
        result = finish(flow)
        assert result["status"] == "authorized" and not result["report_data_ingested"]
        assert "SYNTHETIC" not in str(result)
    with pytest.raises(ads.Conflict): finish(flow)
    assert sum(url.endswith("access_token/") for url in calls) == 1
    flow[3].refresh_from_db()
    assert flow[3].status == ("unknown" if timeout else "authorized")


def test_legacy_entry_disabled_without_claim_or_fetch(flow):
    with pytest.raises(ads.LegacyCallbackGone) as exc:
        ads.complete(flow[0], flow[3].pk, "a" * 64)
    assert exc.value.status_code == 410
    flow[3].refresh_from_db()
    assert flow[3].consumed_at is None
    ads.PlatformHttpClient.request.assert_not_called()


@pytest.mark.parametrize("value", ["", "http://saas.example.test" + direct.CALLBACK_PATH,
    CALLBACK + "?", CALLBACK + "#", CALLBACK + "?x=1", CALLBACK + "#x", CALLBACK + "/",
    "https://user@saas.example.test" + direct.CALLBACK_PATH])
def test_new_start_never_falls_back(flow, settings, value):
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = value
    with pytest.raises(ValidationError): ads.start(flow[0], flow[1].pk, flow[2].pk, VERIFIER)
    assert AdsOAuthSession.objects.count() == 1


@pytest.mark.parametrize("verifier", [None, "x" * 42, "x" * 129, "!" * 64])
def test_start_requires_valid_nonce(flow, verifier):
    with pytest.raises(ValidationError): ads.start(flow[0], flow[1].pk, flow[2].pk, verifier)
    assert AdsOAuthSession.objects.count() == 1


def test_denial_never_exchanges(flow, monkeypatch):
    params = {"state": flow[5]["state"], "error": "authorization_denied"}
    assert finish(flow, callback_params=params)["status"] == "failed"
    ads.PlatformHttpClient.request.assert_not_called()
    flow[6].retrieve_secret.assert_not_called()


def expire(session, status=None):
    changes = {"expires_at": timezone.now() - timedelta(seconds=1)}
    if status:
        changes["status"] = status
    AdsOAuthSession.objects.filter(pk=session.pk).update(**changes)


@pytest.mark.parametrize("failure", ["response_loss", "process_crash", "row_save", "audit_rollback"])
def test_orphan_recovery_closes_before_lookup_and_revoke(flow, monkeypatch, failure):
    session, backend = flow[3], flow[6]
    refs = {"credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    stored = {}
    events = []
    def store(**kwargs):
        assert kwargs["operation_id"] == kwargs["idempotency_key"] == "ads-" + str(session.pk)
        durable = AdsOAuthSession.objects.get(pk=session.pk)
        assert durable.status == "exchanging" and durable.consumed_at
        stored.update(refs)
        if failure == "response_loss": raise TimeoutError("stored but response lost")
        if failure == "process_crash": raise SystemExit("stored then process died")
        return refs
    backend.store_secrets.side_effect = store
    original_save, original_audit = AdsOAuthSession.save, ads.audit
    def save(record, *args, **kwargs):
        if failure == "row_save" and record.status == "authorized": raise RuntimeError("synthetic")
        return original_save(record, *args, **kwargs)
    def audit(record, actor, event, result="success"):
        if failure == "audit_rollback" and event == "authorized": raise RuntimeError("synthetic")
        return original_audit(record, actor, event, result)
    monkeypatch.setattr(AdsOAuthSession, "save", save)
    monkeypatch.setattr(ads, "audit", audit)
    network = Mock(return_value={"access_token": "SYNTHETIC_TOKEN"})
    monkeypatch.setattr(ads, "request_json", network)
    with pytest.raises(SystemExit if failure == "process_crash" else ValidationError): finish(flow)
    session.refresh_from_db()
    assert not session.token_id
    def lookup(operation, *, close=False):
        assert close and operation == ads.operation_id(session)
        events.append("closed")
        return {"found": True, **stored}
    def revoke(credential_id, token_id):
        assert events == ["closed"]
        assert (credential_id, token_id) == (refs["credential_id"], refs["token_id"])
        events.append("revoked")
        return {"status": "revoked"}
    backend.lookup_reference_by_operation.side_effect = lookup
    backend.revoke.side_effect = revoke
    expire(session)
    AdsOAuthSession.objects.filter(pk=session.pk).update(consumed_at=timezone.now() - timedelta(minutes=3))
    assert ads.cleanup_ads_authorizations()["cleaned"] == 1
    session.refresh_from_db()
    assert session.status == "cleaned" and session.token_id == refs["token_id"]
    assert events == ["closed", "revoked"]
    assert network.call_count == 1
    assert ads.cleanup_ads_authorizations()["claimed"] == 0
    backend.store_secrets.assert_called_once()


@pytest.mark.parametrize("status", ["authorized", "unknown", "cancelled", "exchanging"])
def test_cleanup_retry_and_lease_fencing(flow, status):
    session, backend = flow[3], flow[6]
    expire(session, status)
    AdsOAuthSession.objects.filter(pk=session.pk).update(consumed_at=timezone.now() - timedelta(minutes=3))
    backend.lookup_reference_by_operation.side_effect = TimeoutError("synthetic")
    assert ads.cleanup_ads_authorizations(limit=1)["retry"] == 1
    session.refresh_from_db()
    assert session.status == "cleanup_pending" and session.cleanup_attempts == 1 and session.cleanup_error
    backend.lookup_reference_by_operation.side_effect = None
    backend.lookup_reference_by_operation.return_value = {"found": False}
    assert ads.cleanup_ads_authorizations(limit=1)["cleaned"] == 1
    session.refresh_from_db()
    assert session.cleanup_attempts == 2 and not session.cleanup_error
    backend.revoke.assert_not_called()


def test_cleanup_never_revokes_disabled_mapping(flow):
    from apps.integrations.models import TikTokAdsAdvertiserMapping
    actor, store, config, session, _, _, backend = flow
    refs = {"credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    TikTokAdsAdvertiserMapping.objects.create(tenant=actor.tenant, store=store, integration_config=config,
        advertiser_id="123", token_id=refs["token_id"], currency="PHP", timezone="Asia/Manila", enabled=False)
    expire(session, "unknown")
    backend.lookup_reference_by_operation.return_value = {"found": True, **refs}
    assert ads.cleanup_ads_authorizations()["owned"] == 1
    session.refresh_from_db()
    assert session.status == "cleanup_owned"
    backend.revoke.assert_not_called()


@pytest.mark.parametrize("status", ["authorized", "unknown", "cancelled", "cleanup_pending", "exchanging"])
def test_new_cleanup_does_not_claim_historical_legacy_sessions(flow, status):
    session, backend = flow[3], flow[6]
    expire(session, status)
    AdsOAuthSession.objects.filter(pk=session.pk).update(callback_transport="legacy",
        consumed_at=timezone.now() - timedelta(minutes=3))
    before = AdsOAuthSession.objects.filter(pk=session.pk).values().get()
    assert ads.cleanup_ads_authorizations() == {"claimed": 0, "cleaned": 0, "retry": 0, "owned": 0}
    assert AdsOAuthSession.objects.filter(pk=session.pk).values().get() == before
    backend.lookup_reference_by_operation.assert_not_called()
    backend.revoke.assert_not_called()


def test_active_cleanup_lease_and_bound_sessions_not_claimed(flow):
    session, backend = flow[3], flow[6]
    expire(session, "cleaning")
    AdsOAuthSession.objects.filter(pk=session.pk).update(cleanup_lease_until=timezone.now() + timedelta(minutes=5))
    assert ads.cleanup_ads_authorizations()["claimed"] == 0
    AdsOAuthSession.objects.filter(pk=session.pk).update(status="bound")
    assert ads.cleanup_ads_authorizations()["claimed"] == 0
    backend.lookup_reference_by_operation.assert_not_called()


def test_cleanup_marketplace_reference_owner_protected(flow):
    from apps.integrations.store_authorization_service import create_store_authorization
    actor, store, config, session, _, _, backend = flow
    refs = {"credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    create_store_authorization(tenant=actor.tenant, store=store, integration_config=config,
        platform="tiktok", region=store.country_code, platform_store_id="synthetic-shop",
        merchant_subject_id="synthetic-merchant", shop_cipher="synthetic-shop-cipher",
        credential_id=refs["credential_id"], token_id=refs["token_id"],
        credential_mask={"configured": "********"}, allow_live_references=True, scopes=[], actor=actor)
    expire(session, "unknown")
    backend.lookup_reference_by_operation.return_value = {"found": True, **refs}
    assert ads.cleanup_ads_authorizations()["owned"] == 1
    backend.revoke.assert_not_called()


def test_cleanup_worker_losing_fence_cannot_revoke_or_finish(flow):
    import uuid
    session, backend = flow[3], flow[6]
    expire(session, "unknown")
    replacement_fence = uuid.uuid4()
    def lookup(*args, **kwargs):
        AdsOAuthSession.objects.filter(pk=session.pk).update(cleanup_fence=replacement_fence)
        return {"found": True, "credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    backend.lookup_reference_by_operation.side_effect = lookup
    assert ads.cleanup_ads_authorizations()["claimed"] == 1
    session.refresh_from_db()
    assert session.status == "cleaning" and session.cleanup_fence == replacement_fence
    backend.revoke.assert_not_called()


def test_cleanup_revoke_timeout_durable_retry(flow):
    session, backend = flow[3], flow[6]
    expire(session, "authorized")
    refs = {"credential_id": "cre_" + "c" * 32, "token_id": "tok_" + "d" * 32}
    backend.lookup_reference_by_operation.return_value = {"found": True, **refs}
    backend.revoke.side_effect = TimeoutError("synthetic")
    assert ads.cleanup_ads_authorizations()["retry"] == 1
    session.refresh_from_db()
    assert session.token_id == refs["token_id"] and session.status == "cleanup_pending"
    backend.revoke.side_effect = None
    backend.revoke.return_value = {"status": "revoked"}
    assert ads.cleanup_ads_authorizations()["cleaned"] == 1


def test_cleanup_crash_reclaimed_by_new_fence(flow):
    session, backend = flow[3], flow[6]
    expire(session, "unknown")
    backend.lookup_reference_by_operation.side_effect = SystemExit("cleanup process died")
    with pytest.raises(SystemExit): ads.cleanup_ads_authorizations()
    session.refresh_from_db()
    old_fence = session.cleanup_fence
    assert session.status == "cleaning"
    AdsOAuthSession.objects.filter(pk=session.pk).update(cleanup_lease_until=timezone.now() - timedelta(seconds=1))
    backend.lookup_reference_by_operation.side_effect = None
    backend.lookup_reference_by_operation.return_value = {"found": False}
    assert ads.cleanup_ads_authorizations()["cleaned"] == 1
    session.refresh_from_db()
    assert session.cleanup_fence != old_fence


@pytest.mark.parametrize("status", ["bound", "unknown", "exchanging"])
def test_readonly_expired_status_no_live_gate_or_mutation(flow, settings, monkeypatch, status):
    actor, _, config, session, _, _, _ = flow
    expire(session, status)
    AdsOAuthSession.objects.filter(pk=session.pk).update(consumed_at=timezone.now() - timedelta(minutes=3))
    PlatformIntegrationConfig.objects.filter(pk=config.pk).update(network_enabled=False, config_version=999)
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = ""
    monkeypatch.setattr(ads, "require_live_mode", Mock(side_effect=AssertionError("No live gate for reads")))
    assert ads.load(actor, session.pk, read_only=True).status == status
    session.refresh_from_db()
    assert session.status == status
    monkeypatch.setattr(ads, "integration_values_allowed", lambda *a, **k: False)
    with pytest.raises(PermissionDenied): ads.load(actor, session.pk, read_only=True)
