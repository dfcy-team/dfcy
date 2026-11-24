from datetime import timedelta
from types import SimpleNamespace
import pytest
from django.utils import timezone
from apps.flash_sales import engine,provider
from apps.flash_sales.models import StoreTask
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop,configured

@pytest.mark.django_db
def test_token_wait_preserves_retry_budget_and_resumes(shop,monkeypatch,settings):
    settings.FLASH_SALES_LIVE_ENABLED=True
    user,store,_=shop;configured(shop)
    task=submit(user,request_id="token-wait-budget",store_ids=[store.id]).tasks.get()
    auth=SimpleNamespace(expires_at=timezone.now()-timedelta(seconds=1),
        integration_config=SimpleNamespace(network_enabled=True,status="verified"))
    monkeypatch.setattr(provider,"authorized_store",lambda store:auth)
    monkeypatch.setattr(engine,"step",lambda task,adapter:adapter.call("get_shop_flash_sale_list"))
    for _ in range(5):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        assert engine.run_step(task.id)=="waiting"
    task.refresh_from_db()
    assert task.retry_count==0
    assert task.state.get("verification_failures",0)==0
    assert task.state.get("prewrite_read_failures",0)==0
    assert task.state.get("credential_wait")=="TOKEN_REFRESH_REQUIRED"
    assert task.finished_at is None
    monkeypatch.setattr(engine,"step",lambda task,adapter:("succeeded","test complete"))
    StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
    assert engine.run_step(task.id)=="succeeded"
    task.refresh_from_db()
    assert "credential_wait" not in task.state

from unittest.mock import Mock
from apps.integrations import credential_access as access
from apps.integrations.custody import CustodyError,CustodyReferenceNotFound
from celery.exceptions import WorkerShutdown
from celery.signals import worker_init,beat_init

@pytest.mark.parametrize("code",["RUNTIME_CONFIG_INVALID","CUSTODY_UNAVAILABLE","CREDENTIAL_REFERENCE_MISSING"])
@pytest.mark.django_db
def test_custody_wait_preserves_retry_budget(shop,monkeypatch,settings,code):
    settings.FLASH_SALES_LIVE_ENABLED=True
    user,store,_=shop;configured(shop)
    task=submit(user,request_id="custody-"+code,store_ids=[store.id]).tasks.get()
    auth=SimpleNamespace(expires_at=timezone.now()+timedelta(hours=1),
        integration_config=SimpleNamespace(network_enabled=True,status="verified"))
    monkeypatch.setattr(provider,"authorized_store",lambda store:auth)
    def unavailable():raise access.CredentialAccessError(code)
    monkeypatch.setattr(provider,"checked_custody_backend",unavailable)
    monkeypatch.setattr(engine,"step",lambda task,adapter:adapter.call("get_shop_flash_sale_list"))
    for _ in range(5):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        assert engine.run_step(task.id)=="waiting"
    task.refresh_from_db()
    assert task.retry_count==0
    assert task.state["credential_wait"]==code
    assert task.state.get("verification_failures",0)==0
    assert not task.intents.exists()
    assert task.finished_at is None

def test_shared_credentials_read_same_references():
    custody=Mock();custody.retrieve_secret.return_value="SYNTHETIC_SECRET";custody.retrieve_access_token.return_value="SYNTHETIC_TOKEN"
    config=SimpleNamespace(credential_id="FAKE_APP_REF",platform_config={})
    auth=SimpleNamespace(token_id="FAKE_SHOP_REF",expires_at=timezone.now()+timedelta(hours=1))
    assert access.retrieve_marketplace_credentials(config,auth,custody=custody)==("SYNTHETIC_SECRET","SYNTHETIC_TOKEN")
    custody.retrieve_secret.assert_called_once_with("FAKE_APP_REF")
    custody.retrieve_access_token.assert_called_once_with("FAKE_SHOP_REF")

@pytest.mark.parametrize("error,code",[
    (CustodyError("SYNTHETIC_PRIVATE_DETAIL"),"CUSTODY_UNAVAILABLE"),
    (CustodyReferenceNotFound("SYNTHETIC_PRIVATE_DETAIL"),"CREDENTIAL_REFERENCE_MISSING"),
])
def test_shared_custody_failures_are_safe_and_classified(error,code):
    custody=Mock();custody.retrieve_secret.side_effect=error
    config=SimpleNamespace(credential_id="FAKE_REF",platform_config={})
    auth=SimpleNamespace(token_id="FAKE_TOKEN",expires_at=timezone.now()+timedelta(hours=1))
    with pytest.raises(access.CredentialAccessError) as caught:
        access.retrieve_marketplace_credentials(config,auth,custody=custody)
    assert caught.value.code==code
    assert "SYNTHETIC_PRIVATE_DETAIL" not in str(caught.value)
    custody.retrieve_access_token.assert_not_called()

@pytest.mark.parametrize("offset",[None,-1,0,29,30])
def test_shared_expiry_waits_without_touching_custody(offset):
    now=timezone.now();custody=Mock()
    auth=SimpleNamespace(token_id="FAKE_REF",expires_at=None if offset is None else now+timedelta(seconds=offset))
    with pytest.raises(access.CredentialAccessError,match="既有凭据续期"):
        access.retrieve_marketplace_credentials(SimpleNamespace(),auth,custody=custody,now=now,minimum_validity_seconds=30)
    assert not custody.mock_calls

def test_invalid_runtime_does_not_reach_custody(monkeypatch):
    monkeypatch.setattr(access,"runtime_snapshot",lambda:{"valid":False})
    backend=Mock();monkeypatch.setattr(access,"get_custody_backend",backend)
    with pytest.raises(access.CredentialAccessError) as caught:access.checked_custody_backend()
    assert caught.value.code=="RUNTIME_CONFIG_INVALID"
    backend.assert_not_called()

@pytest.mark.parametrize("signal",[worker_init,beat_init])
def test_invalid_worker_startup_stops_and_reports_safe_code(monkeypatch,settings,signal,caplog):
    settings.DEBUG=False;settings.FLASH_SALES_WORKERS_ENABLED=True
    def invalid():raise access.CredentialAccessError("RUNTIME_CONFIG_INVALID")
    monkeypatch.setattr(access,"checked_custody_backend",invalid)
    close=Mock();monkeypatch.setattr(access.connections,"close_all",close)
    with pytest.raises(WorkerShutdown):signal.send(sender=Mock())
    close.assert_called_once()
    assert "RUNTIME_CONFIG_INVALID" in caplog.text

def test_valid_worker_startup_checks_backend_once(monkeypatch,settings):
    settings.DEBUG=False;settings.FLASH_SALES_WORKERS_ENABLED=True
    backend=Mock();monkeypatch.setattr(access,"checked_custody_backend",backend)
    monkeypatch.setattr(access.connections,"close_all",Mock())
    access.check_worker_credentials()
    backend.assert_called_once()

def test_deployment_check_reports_unusable_custody(monkeypatch,settings):
    settings.DEBUG=False;settings.FLASH_SALES_WORKERS_ENABLED=True
    def invalid():raise access.CredentialAccessError("CUSTODY_NOT_CONFIGURED")
    monkeypatch.setattr(access,"checked_custody_backend",invalid)
    result=access.check_integration_credentials()
    assert len(result)==1 and result[0].id=="integrations.E001"

@pytest.mark.django_db
def test_credential_wait_does_not_leave_unknown_write_or_rebuild(shop):
    from apps.flash_sales.models import WriteOperation
    from tests.test_flash_sales import FakeShopee,drain
    user,store,_=shop;configured(shop)
    task=submit(user,request_id="prewrite-custody-wait",store_ids=[store.id]).tasks.get()
    task.state["rate_limit_wait_since"]=(timezone.now()-timedelta(hours=2)).isoformat()
    task.save(update_fields=["state"])
    class HeldCredentials(FakeShopee):
        held=True
        def call(self,endpoint,*,body):
            if self.held:
                raise provider.CredentialWait(access.CredentialAccessError("CUSTODY_UNAVAILABLE"))
            return super().call(endpoint,body=body)
    adapter=HeldCredentials()
    for _ in range(6):
        StoreTask.objects.filter(pk=task.id).update(next_attempt_at=None)
        engine.run_step(task.id,adapter=adapter)
    task.refresh_from_db()
    assert task.status=="waiting" and task.retry_count==0
    assert not task.state.get("retry_paused")
    assert task.intents.count()==1
    assert task.intents.get().result.get("execution_attempt",0)==0
    assert WriteOperation.objects.get().status=="prepared"
    assert adapter.calls==[]
    adapter.held=False
    drain(task,adapter,count=12)
    assert task.status=="succeeded"
    assert sum(endpoint=="create_shop_flash_sale" for endpoint,_ in adapter.calls)==1

def test_missing_ca_mount_is_configuration_error(monkeypatch,settings,tmp_path):
    settings.DEBUG=False
    monkeypatch.setattr(access,"runtime_snapshot",lambda:{"valid":True,"config":{"custody":{"backend":"http","ca_file_path":str(tmp_path/"absent-ca.pem")}}})
    backend=Mock();monkeypatch.setattr(access,"get_custody_backend",backend)
    with pytest.raises(access.CredentialAccessError) as caught:access.checked_custody_backend()
    assert caught.value.code=="CUSTODY_NOT_CONFIGURED"
    backend.assert_not_called()

def test_refusing_backend_cannot_pass_live_readiness(monkeypatch,settings):
    from apps.integrations.custody import RefusingCustodyBackend
    settings.DEBUG=False
    monkeypatch.setattr(access,"runtime_snapshot",lambda:{"valid":True,"config":{"custody":{"backend":"http"}}})
    monkeypatch.setattr(access,"get_custody_backend",lambda:RefusingCustodyBackend())
    with pytest.raises(access.CredentialAccessError) as caught:access.checked_custody_backend()
    assert caught.value.code=="CUSTODY_NOT_CONFIGURED"
