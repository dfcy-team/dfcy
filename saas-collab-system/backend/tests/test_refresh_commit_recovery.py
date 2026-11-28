from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.db import DatabaseError
from django.utils import timezone
from apps.integrations import automatic_refresh as automatic, marketplace_oauth_service as oauth, store_authorization_service as references
from apps.integrations.models import MarketplaceStoreAuthorization,AutomaticRefreshAttempt,authorization_service_write
from tests.test_flash_sales import shop

@pytest.mark.django_db(transaction=True)
def test_saved_token_survives_failed_reference_commit_and_retry_does_not_refresh(shop,monkeypatch):
    actor,store,_=shop
    auth=MarketplaceStoreAuthorization.objects.get(store=store,platform="shopee")
    with authorization_service_write():
        auth.expires_at=timezone.now()+timedelta(minutes=5)
        auth.save(update_fields=["expires_at"])
    monkeypatch.setattr(automatic,"get_runtime_platform_config",lambda p:{"auto_refresh_enabled":True})
    revoker=Mock(return_value={"status":"revoked"})
    result={"credential_id":"cred_"+"a"*32,"token_id":"tok_"+"b"*32,"reference_version":auth.credential_reference_version+1,
            "expires_at":timezone.now()+timedelta(hours=4),"reference_kind":"custody",
            "previous_reference_revoker":revoker,"new_reference_revoker":revoker}
    provider=Mock()
    provider.refresh_authorization.return_value=result
    monkeypatch.setattr(oauth,"resolve_oauth_provider",lambda *a:provider)
    from apps.integrations import refresh_commit_recovery as recovery
    custody=Mock()
    custody.lookup_reference_by_operation.return_value={"found":True,"status":"active",**result}
    custody.revoke=revoker
    monkeypatch.setattr(recovery,"get_custody_backend",lambda:custody)
    original=references._audit
    def failed(*args,**kwargs):
        if len(args)>2 and args[2]=="rotate_reference_prepare":raise DatabaseError("SYNTHETIC_PRIVATE_DATABASE_DETAIL")
        return original(*args,**kwargs)
    monkeypatch.setattr(references,"_audit",failed)
    assert automatic.refresh_due_authorizations()["failed"]==1
    revoker.assert_not_called()
    attempt=AutomaticRefreshAttempt.objects.get()
    assert attempt.failure_category=="commit_pending"
    assert attempt.commit_recovery["phase"]=="commit_pending"
    assert "SYNTHETIC_PRIVATE_DATABASE_DETAIL" not in str(attempt.commit_recovery)
    monkeypatch.setattr(references,"_audit",original)
    AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["success"]==1
    auth.refresh_from_db()
    assert auth.token_id==result["token_id"]
    assert provider.refresh_authorization.call_count==1

from types import SimpleNamespace
from apps.integrations import refresh_commit_recovery as recovery
from apps.integrations.models import IntegrationAuditLog
from apps.integrations.oauth_errors import OAuthFlowError,OAUTH_PROVIDER_UNAVAILABLE,OAUTH_AUTH_REJECTED

@pytest.fixture
def case(shop,monkeypatch):
    actor,store,_=shop
    auth=MarketplaceStoreAuthorization.objects.get(store=store,platform="shopee")
    with authorization_service_write():
        auth.expires_at=timezone.now()+timedelta(minutes=5)
        auth.save(update_fields=["expires_at"])
    monkeypatch.setattr(automatic,"get_runtime_platform_config",lambda p:{"auto_refresh_enabled":True})
    revoke=Mock(return_value={"status":"revoked"})
    result={"credential_id":"cred_"+"c"*32,"token_id":"tok_"+"d"*32,
        "reference_version":auth.credential_reference_version+1,"expires_at":timezone.now()+timedelta(hours=4),
        "reference_kind":"custody","previous_reference_revoker":revoke,"new_reference_revoker":revoke}
    provider=Mock();provider.refresh_authorization.return_value=result
    custody=Mock();custody.lookup_reference_by_operation.return_value={"found":True,"status":"active",**result};custody.revoke=revoke
    monkeypatch.setattr(oauth,"resolve_oauth_provider",lambda *a:provider)
    monkeypatch.setattr(recovery,"get_custody_backend",lambda:custody)
    return SimpleNamespace(actor=actor,auth=auth,provider=provider,custody=custody,result=result,revoke=revoke)

def fail_commit(monkeypatch):
    original=references._audit
    def failed(*args,**kwargs):
        if len(args)>2 and args[2]=="rotate_reference_prepare":raise DatabaseError(1205,"SYNTHETIC_PRIVATE_SQL")
        return original(*args,**kwargs)
    monkeypatch.setattr(references,"_audit",failed)
    return original

@pytest.mark.django_db(transaction=True)
def test_pending_commit_wait_is_bounded_and_does_not_reexchange(case,monkeypatch):
    fail_commit(monkeypatch)
    for _ in range(automatic.MAX_REFRESH_ATTEMPTS):
        automatic.refresh_due_authorizations()
        AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    attempt=AutomaticRefreshAttempt.objects.get()
    assert case.provider.refresh_authorization.call_count==1
    assert attempt.attempt_count==automatic.MAX_REFRESH_ATTEMPTS
    assert automatic.refresh_due_authorizations()["attempted"]==0
    case.revoke.assert_not_called()
    detail=IntegrationAuditLog.objects.filter(action="automatic_refresh").latest("created_at").masked_detail
    assert detail["failure_category"]=="commit_pending" and detail["token_saved"] is True
    assert detail["database_error_number"]==1205
    assert "SYNTHETIC_PRIVATE_SQL" not in str(detail)
    assert case.result["token_id"] not in str(detail)

@pytest.mark.django_db(transaction=True)
def test_manual_refresh_cannot_duplicate_automatic_recovery(case,monkeypatch):
    original=fail_commit(monkeypatch)
    automatic.refresh_due_authorizations()
    monkeypatch.setattr(references,"_audit",original)
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError,match="自动恢复"):
        oauth.refresh_marketplace_authorization(case.auth,actor=case.actor)
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1

@pytest.mark.django_db(transaction=True)
def test_stale_exchange_lease_recovers_custody_receipt_without_exchange(case,monkeypatch):
    original=fail_commit(monkeypatch)
    automatic.refresh_due_authorizations()
    attempt=AutomaticRefreshAttempt.objects.get();data=attempt.commit_recovery
    data.pop("candidate");data.pop("recover_only",None)
    data.update(phase="exchange_in_flight",lease_until=(timezone.now()-timedelta(seconds=1)).isoformat())
    AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(status="running",next_retry_at=None,commit_recovery=data)
    monkeypatch.setattr(references,"_audit",original)
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1
    assert case.custody.lookup_reference_by_operation.call_args.kwargs["include_reference"] is True

@pytest.mark.django_db(transaction=True)
def test_live_lease_prevents_second_claim(case,monkeypatch):
    fail_commit(monkeypatch);automatic.refresh_due_authorizations()
    attempt=AutomaticRefreshAttempt.objects.get();data=attempt.commit_recovery
    data["lease_until"]=(timezone.now()+timedelta(minutes=5)).isoformat()
    AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(commit_recovery=data,next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["attempted"]==0
    assert case.provider.refresh_authorization.call_count==1

@pytest.mark.parametrize("status",["revoked","expired"])
@pytest.mark.django_db(transaction=True)
def test_inactive_receipt_never_rebound_or_refreshed(case,monkeypatch,status):
    original=fail_commit(monkeypatch);automatic.refresh_due_authorizations()
    monkeypatch.setattr(references,"_audit",original)
    case.custody.lookup_reference_by_operation.return_value={"found":True,"status":status,**case.result}
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["failed"]==1
    case.auth.refresh_from_db()
    assert case.auth.token_id!=case.result["token_id"]
    assert case.provider.refresh_authorization.call_count==1
    assert automatic.refresh_due_authorizations()["attempted"]==0

@pytest.mark.django_db(transaction=True)
def test_response_loss_uses_saved_operation_receipt(case):
    error=OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE,"SYNTHETIC_PRIVATE_WIRE")
    error.stage="save_token";error.category="timeout_uncertain"
    case.provider.refresh_authorization.side_effect=error
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1
    case.auth.refresh_from_db()
    assert case.auth.token_id==case.result["token_id"]

@pytest.mark.django_db(transaction=True)
def test_missing_receipt_after_unknown_exchange_never_replayed(case):
    error=OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE,"SYNTHETIC_PRIVATE_WIRE")
    error.stage="exchange_token";error.category="timeout_uncertain"
    case.provider.refresh_authorization.side_effect=error
    case.custody.lookup_reference_by_operation.return_value={"found":False}
    assert automatic.refresh_due_authorizations()["failed"]==1
    assert automatic.refresh_due_authorizations()["attempted"]==0
    assert case.provider.refresh_authorization.call_count==1
    assert AutomaticRefreshAttempt.objects.get().failure_category=="rotation_uncertain"

@pytest.mark.django_db(transaction=True)
def test_definitive_rejection_keeps_reauthorization_classification(case):
    error=OAuthFlowError(OAUTH_AUTH_REJECTED,"SYNTHETIC_PRIVATE_WIRE")
    error.stage="exchange_token"
    case.provider.refresh_authorization.side_effect=error
    case.custody.lookup_reference_by_operation.return_value={"found":False}
    automatic.refresh_due_authorizations()
    attempt=AutomaticRefreshAttempt.objects.get()
    assert attempt.failure_category=="authorization_rejected" and attempt.next_retry_at is None
    assert automatic.refresh_due_authorizations()["attempted"]==0

@pytest.mark.django_db(transaction=True)
def test_application_binding_change_cannot_adopt_saved_reference(case,monkeypatch):
    original=fail_commit(monkeypatch);automatic.refresh_due_authorizations()
    monkeypatch.setattr(references,"_audit",original)
    config=case.auth.integration_config
    config.platform_config={**config.platform_config,"partner_id":"DIFFERENT_SYNTHETIC_APP"}
    config.save(update_fields=["platform_config"])
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["failed"]==1
    case.auth.refresh_from_db()
    assert case.auth.token_id!=case.result["token_id"]
    assert case.provider.refresh_authorization.call_count==1

@pytest.mark.django_db(transaction=True)
def test_changed_receipt_cannot_adopt_foreign_reference(case,monkeypatch):
    original=fail_commit(monkeypatch);automatic.refresh_due_authorizations()
    monkeypatch.setattr(references,"_audit",original)
    case.custody.lookup_reference_by_operation.return_value={"found":True,"status":"active",**case.result,
        "token_id":"tok_"+"e"*32}
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["failed"]==1
    case.auth.refresh_from_db()
    assert case.auth.token_id!=case.result["token_id"]
    assert case.provider.refresh_authorization.call_count==1

@pytest.mark.django_db(transaction=True)
def test_legacy_uncertain_rotation_not_reopened(case):
    AutomaticRefreshAttempt.objects.create(request_key=automatic._attempt_key(case.auth),tenant_id=case.auth.tenant_id,
        status="failed",failure_category="rotation_uncertain")
    assert automatic.refresh_due_authorizations()["attempted"]==0
    case.provider.refresh_authorization.assert_not_called()

@pytest.mark.django_db(transaction=True)
def test_lost_commit_acknowledgment_is_reconciled_without_exchange(case,monkeypatch):
    original=recovery._commit
    def acknowledged_late(*args,**kwargs):
        original(*args,**kwargs)
        raise DatabaseError("SYNTHETIC_LOST_COMMIT_ACK")
    monkeypatch.setattr(recovery,"_commit",acknowledged_late)
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1
    assert AutomaticRefreshAttempt.objects.get().commit_recovery["phase"]=="committed"

@pytest.mark.django_db(transaction=True)
def test_candidate_journal_save_failure_retains_receipt_and_retries_commit(case,monkeypatch):
    original=recovery._persist
    failed=False
    def once(attempt,data,phase):
        nonlocal failed
        if phase=="commit_pending" and not failed:
            failed=True
            raise DatabaseError("SYNTHETIC_JOURNAL_COMMIT_FAILURE")
        return original(attempt,data,phase)
    monkeypatch.setattr(recovery,"_persist",once)
    assert automatic.refresh_due_authorizations()["failed"]==1
    case.revoke.assert_not_called()
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1

def test_complete_http_receipt_preserves_version_expiry_without_secret_values():
    from apps.integrations.custody import HttpCustodyBackend
    custody=object.__new__(HttpCustodyBackend)
    expiry=(timezone.now()+timedelta(hours=1)).isoformat()
    custody._request_json=Mock(return_value={"found":True,"status":"active",
        "credential_id":"cred_"+"a"*32,"token_id":"tok_"+"b"*32,"version":7,"expires_at":expiry,
        "access_token":"SYNTHETIC_ACCESS_VALUE","refresh_token":"SYNTHETIC_REFRESH_VALUE"})
    complete=custody.lookup_reference_by_operation("synthetic-operation",include_reference=True)
    assert complete["reference_version"]==7 and complete["expires_at"]==expiry
    assert "SYNTHETIC_ACCESS_VALUE" not in str(complete) and "SYNTHETIC_REFRESH_VALUE" not in str(complete)
    assert set(custody.lookup_reference_by_operation("synthetic-operation"))=={"found","credential_id","token_id","status"}

@pytest.mark.parametrize("platform",["shopee","lazada","tiktok"])
@pytest.mark.parametrize("journaled",[True,False])
def test_provider_attaches_operation_only_to_journaled_refresh(platform,journaled):
    from apps.integrations import live_providers
    cls={"shopee":live_providers.ShopeeLiveOAuthProvider,"lazada":live_providers.LazadaLiveOAuthProvider,
         "tiktok":live_providers.TikTokLiveOAuthProvider}[platform]
    obj=object.__new__(cls)
    obj._preflight=Mock();obj.config={"refresh_path":"/synthetic"}
    obj.custody=Mock();obj.custody.retrieve_refresh_token.return_value="SYNTHETIC_REFRESH_VALUE"
    obj._host=Mock(return_value="https://platform.example.test")
    obj._app_id=Mock(return_value="123");obj._app_secret=Mock(return_value="SYNTHETIC_APP_SECRET")
    obj._market=Mock(return_value="PH");obj._signed_public_query=Mock(return_value={})
    payload={"access_token":"SYNTHETIC_ACCESS_VALUE","refresh_token":"SYNTHETIC_REFRESH_VALUE",
        "expire_in":3600,"expires_in":3600,"access_token_expire_in":3600,"granted_scopes":["base"]}
    obj._request_json=Mock(return_value=payload)
    obj._token_request=Mock(return_value=(payload,{}) if platform=="tiktok" else payload)
    obj._store_tokens=Mock(return_value={"credential_id":"FAKE_CREDENTIAL_REF","token_id":"FAKE_TOKEN_REF"})
    auth=SimpleNamespace(token_id="FAKE_OLD_REF",platform_store_id="456",region="PH",scopes=["base"],credential_reference_version=1)
    if journaled:auth._refresh_operation_id="synthetic-durable-attempt"
    obj.refresh_authorization(auth)
    args=obj._store_tokens.call_args.kwargs
    if journaled:
        assert args["operation_id"]=="synthetic-durable-attempt" and args["idempotency_key"]==args["operation_id"]
    else:
        assert "operation_id" not in args and "idempotency_key" not in args

@pytest.mark.django_db(transaction=True)
def test_real_custody_journal_keeps_new_reference_until_commit(case,monkeypatch,tmp_path):
    from apps.integrations.custody import FileCustodyBackend
    custody=FileCustodyBackend(tmp_path/"synthetic-only-vault")
    old=custody.store_secrets(credential_type="shopee",access_token="PLACEHOLDER_OLD_ACCESS",
        refresh_token="PLACEHOLDER_OLD_REFRESH",reference_version=case.auth.credential_reference_version,
        expires_at=(timezone.now()+timedelta(minutes=5)).isoformat())
    with authorization_service_write():
        case.auth.credential_id=old["credential_id"];case.auth.token_id=old["token_id"]
        case.auth.save(update_fields=["credential_id","token_id"])
    def exchange(auth):
        refs=custody.store_secrets(credential_type="shopee",reference_version=auth.credential_reference_version+1,
            access_token="PLACEHOLDER_NEW_ACCESS",refresh_token="PLACEHOLDER_NEW_REFRESH",
            expires_at=(timezone.now()+timedelta(hours=4)).isoformat(),
            operation_id=auth._refresh_operation_id,idempotency_key=auth._refresh_operation_id)
        return {**refs,"reference_kind":"custody","previous_reference_revoker":custody.revoke,
                "new_reference_revoker":custody.revoke}
    case.provider.refresh_authorization.side_effect=exchange
    monkeypatch.setattr(recovery,"get_custody_backend",lambda:custody)
    original=fail_commit(monkeypatch)
    assert automatic.refresh_due_authorizations()["failed"]==1
    attempt=AutomaticRefreshAttempt.objects.get()
    found=custody.lookup_reference_by_operation(attempt.commit_recovery["operation_id"])
    assert found["status"]=="active" and found["token_id"]!=old["token_id"]
    assert "SYNTHETIC_NEW" not in str(attempt.commit_recovery)
    monkeypatch.setattr(references,"_audit",original)
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1
    case.auth.refresh_from_db()
    assert case.auth.token_id==found["token_id"]
    assert custody.retrieve_access_token(case.auth.token_id)=="PLACEHOLDER_NEW_ACCESS"

@pytest.mark.django_db(transaction=True)
def test_platform_exchange_runs_outside_authorization_transaction(case):
    from django.db import connection
    def exchange(auth):
        assert not connection.in_atomic_block
        return case.result
    case.provider.refresh_authorization.side_effect=exchange
    assert automatic.refresh_due_authorizations()["success"]==1

@pytest.mark.django_db(transaction=True)
def test_stale_manual_generation_cannot_refresh_during_new_ownership(case):
    from rest_framework.exceptions import ValidationError
    with authorization_service_write():
        MarketplaceStoreAuthorization.objects.filter(pk=case.auth.pk).update(token_id="FAKE_NEW_GENERATION_REF")
    with pytest.raises(ValidationError,match="令牌已变化"):
        oauth.refresh_marketplace_authorization(case.auth,actor=case.actor)
    case.provider.refresh_authorization.assert_not_called()

@pytest.mark.django_db(transaction=True)
def test_transient_receipt_lookup_is_automatically_retried_without_exchange(case,monkeypatch):
    from apps.integrations.custody import CustodyError
    original=fail_commit(monkeypatch);automatic.refresh_due_authorizations()
    monkeypatch.setattr(references,"_audit",original)
    case.custody.lookup_reference_by_operation.side_effect=CustodyError("SYNTHETIC_CUSTODY_OUTAGE")
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["failed"]==1
    assert AutomaticRefreshAttempt.objects.get().failure_category=="commit_pending"
    case.custody.lookup_reference_by_operation.side_effect=None
    AutomaticRefreshAttempt.objects.update(next_retry_at=timezone.now()-timedelta(seconds=1))
    assert automatic.refresh_due_authorizations()["success"]==1
    assert case.provider.refresh_authorization.call_count==1

def test_commit_snapshot_never_persists_provider_supplied_secret_mask():
    value=recovery._candidate({"credential_id":"cred_"+"a"*32,"token_id":"tok_"+"b"*32,
        "reference_version":2,"expires_at":timezone.now()+timedelta(hours=1),
        "credential_mask":{"unexpected":"SYNTHETIC_RAW_TOKEN_VALUE"}})
    assert "SYNTHETIC_RAW_TOKEN_VALUE" not in str(value)
    assert value["credential_mask"]=={"configured":"********"}
