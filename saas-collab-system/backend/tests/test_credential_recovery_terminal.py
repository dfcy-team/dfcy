from datetime import timedelta
from unittest.mock import Mock
import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.integrations import automatic_refresh as automatic,marketplace_oauth_service as oauth
from apps.integrations.models import AutomaticRefreshAttempt,MarketplaceStoreAuthorization,authorization_service_write
from apps.flash_sales import engine,provider
from apps.flash_sales.models import StoreTask,StoreLock
from apps.flash_sales.services import submit
from tests.test_flash_sales import shop,configured
from tests.test_refresh_commit_recovery import case
from tests.test_rejected_refresh_manual_retry import rejected_journal

@pytest.mark.django_db(transaction=True)
def test_stopped_recovery_does_not_claim_to_be_running(case,monkeypatch):
    data=rejected_journal(case);data.update(phase='commit_pending',candidate={'expires_at':(timezone.now()-timedelta(hours=1)).isoformat()})
    AutomaticRefreshAttempt.objects.create(request_key=automatic._attempt_key(case.auth),tenant=case.auth.tenant,
        status='failed',failure_category='rotation_uncertain',finished_at=timezone.now(),commit_recovery=data)
    monkeypatch.setattr(automatic,'get_runtime_platform_config',lambda p:{'auto_refresh_enabled':True})
    with pytest.raises(ValidationError,match='自动恢复已停止'):
        oauth.refresh_marketplace_authorization(case.auth,actor=case.actor)
    case.provider.refresh_authorization.assert_not_called()

@pytest.mark.django_db
@pytest.mark.parametrize('state',['manual_recovery','blocked','disabled'])
def test_expired_unrecoverable_authorization_finishes_queued_batches(shop,monkeypatch,settings,state):
    settings.FLASH_SALES_LIVE_ENABLED=True
    user,store,_=shop;configured(shop)
    a=MarketplaceStoreAuthorization.objects.get(store=store,platform='shopee')
    with authorization_service_write():
        a.expires_at=timezone.now()-timedelta(hours=1);a.save(update_fields=['expires_at'])
    a.integration_config.network_enabled=True; a.integration_config.status='verified'
    monkeypatch.setattr(provider,'authorized_store',lambda store:a)
    if state == 'disabled':
        monkeypatch.setattr(automatic, 'get_runtime_platform_config', lambda platform: {'auto_refresh_enabled': False})
        def actual_disabled_state(record):
            result = automatic.credential_refresh_state(record)
            assert result['state'] == 'disabled' and result['requires_manual_recovery'] is False
            return result
        monkeypatch.setattr(provider, 'credential_refresh_state', actual_disabled_state)
    else:
        monkeypatch.setattr(provider,'credential_refresh_state',lambda a:{'state':state,'requires_manual_recovery':True})
    custody=Mock();monkeypatch.setattr(provider,'checked_custody_backend',custody)
    monkeypatch.setattr(engine,'step',lambda task,adapter:adapter.call('get_shop_flash_sale_list'))
    tasks=[submit(user,request_id='manual-recovery-'+str(i),store_ids=[store.pk]).tasks.get() for i in range(2)]
    StoreTask.objects.filter(pk=tasks[0].pk).update(status='waiting',state={'credential_wait':'TOKEN_REFRESH_REQUIRED'})
    StoreLock.objects.update_or_create(store=store,defaults={'tenant':store.tenant,'task':tasks[0]})
    for t in tasks:
        assert engine.run_step(t.pk)=='failed'
        t.refresh_from_db();t.batch.refresh_from_db()
        assert t.finished_at and t.batch.finished_at
        assert '需人工恢复' in t.message and not t.intents.exists()
        assert not StoreLock.objects.filter(task=t).exists()
        assert t.retry_count==0 and t.next_attempt_at is None
    custody.assert_not_called()
