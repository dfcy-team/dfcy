from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations.custody import CustodyError, CustodyReferenceNotFound
from apps.integrations.credential_access import (
    CredentialAccessError,
    beat_init,
    check_integration_credentials,
    check_worker_credentials,
    retrieve_marketplace_credentials,
    worker_init,
)
from tests.test_flash_sales import shop


def test_missing_expired_and_near_expiry_tokens_are_rejected_without_custody():
    now = timezone.now()
    for expiry in (None, now - timedelta(seconds=1), now + timedelta(seconds=29)):
        custody = Mock()
        authorization = SimpleNamespace(expires_at=expiry, token_id="synthetic-token")
        config = SimpleNamespace(credential_id="synthetic-secret", platform_config={})
        with pytest.raises(CredentialAccessError) as caught:
            retrieve_marketplace_credentials(
                config, authorization, custody=custody,
                minimum_validity_seconds=30, now=now,
            )
        assert caught.value.code == "TOKEN_REFRESH_REQUIRED"
        custody.retrieve_secret.assert_not_called()
        custody.retrieve_access_token.assert_not_called()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (CustodyReferenceNotFound("synthetic private detail"), "CREDENTIAL_REFERENCE_MISSING"),
        (CustodyError("synthetic private detail"), "CUSTODY_UNAVAILABLE"),
    ],
)
def test_custody_failures_are_sanitized(failure, expected):
    now = timezone.now()
    custody = Mock()
    custody.retrieve_secret.side_effect = failure
    authorization = SimpleNamespace(expires_at=now + timedelta(days=1), token_id="synthetic-token")
    config = SimpleNamespace(credential_id="synthetic-secret", platform_config={})
    with pytest.raises(CredentialAccessError) as caught:
        retrieve_marketplace_credentials(config, authorization, custody=custody, now=now)
    assert caught.value.code == expected
    assert "synthetic private detail" not in str(caught.value)
    custody.retrieve_access_token.assert_not_called()


def test_deploy_check_and_worker_beat_readiness_guards_are_registered(settings, monkeypatch):
    from apps.integrations import credential_access

    settings.DEBUG = False
    settings.FLASH_SALES_WORKERS_ENABLED = True
    monkeypatch.setattr(credential_access, "checked_custody_backend", lambda: object())
    assert check_integration_credentials() == []
    assert any(receiver[1] is check_worker_credentials for receiver in worker_init.receivers)
    assert any(receiver[1] is check_worker_credentials for receiver in beat_init.receivers)
    check_worker_credentials()


@pytest.mark.parametrize("expiry_delta", [None, -1, 29])
@pytest.mark.django_db
def test_flash_credential_wait_fails_before_http(shop, settings, monkeypatch, expiry_delta):
    from apps.flash_sales.provider import CredentialWait, ShopeeAdapter
    from apps.flash_sales import provider

    settings.FLASH_SALES_LIVE_ENABLED = True
    _, store, _ = shop
    expiry = None if expiry_delta is None else timezone.now() + timedelta(seconds=expiry_delta)
    auth = SimpleNamespace(expires_at=expiry, platform_store_id="synthetic-shop", token_id="synthetic-token",
                           integration_config=SimpleNamespace(network_enabled=True, status="verified",
                           credential_id="synthetic-secret", platform_config={"partner_id": "synthetic"}))
    monkeypatch.setattr(provider, "authorized_store", lambda *_args, **_kwargs: auth)
    monkeypatch.setattr(provider, "get_runtime_platform_config", lambda *_args, **_kwargs: {"api_host": "https://partner.shopeemobile.com"})
    monkeypatch.setattr(provider, "PlatformHttpClient", SimpleNamespace(request=Mock()))
    with pytest.raises(CredentialWait) as caught:
        ShopeeAdapter(store).call("get_shop_flash_sale_list")
    assert caught.value.code == "TOKEN_REFRESH_REQUIRED"
    provider.PlatformHttpClient.request.assert_not_called()


@pytest.mark.django_db
def test_credential_wait_does_not_spend_flash_retry_budget(shop, monkeypatch):
    from apps.flash_sales import engine
    from apps.flash_sales.models import StoreTask
    from apps.flash_sales.provider import CredentialWait
    from apps.flash_sales.services import submit
    from tests.test_flash_sales import configured

    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="credential-wait-no-budget", store_ids=[store.pk]).tasks.get()
    monkeypatch.setattr(
        engine, "step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CredentialWait(CredentialAccessError("TOKEN_REFRESH_REQUIRED"))
        ),
    )
    assert engine.run_step(task.pk, adapter=object()) == "waiting"
    task.refresh_from_db()
    assert task.retry_count == 0
    assert task.state["credential_wait"] == "TOKEN_REFRESH_REQUIRED"
    assert not task.state.get("retry_paused")
    assert task.next_attempt_at > timezone.now()


@pytest.mark.django_db
def test_credential_wait_preserves_existing_rate_limit_latch(shop, monkeypatch):
    from apps.flash_sales import engine
    from apps.flash_sales.models import StoreTask
    from apps.flash_sales.provider import CredentialWait
    from apps.flash_sales.services import submit
    from tests.test_flash_sales import configured

    configured(shop)
    user, store, _ = shop
    task = submit(user, request_id="credential-wait-existing-rate-latch", store_ids=[store.pk]).tasks.get()
    since = (timezone.now() - timedelta(minutes=61)).isoformat()
    StoreTask.objects.filter(pk=task.pk).update(state={"rate_limit_wait_since": since})
    monkeypatch.setattr(
        engine, "step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CredentialWait(CredentialAccessError("CUSTODY_UNAVAILABLE"))
        ),
    )
    assert engine.run_step(task.pk, adapter=object()) == "waiting"
    task.refresh_from_db()
    assert task.retry_count == 0
    assert task.state["rate_limit_wait_since"] == since
    assert task.state["retry_paused"] is True  # existing one-hour latch behavior is not weakened
