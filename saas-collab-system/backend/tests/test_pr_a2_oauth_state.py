from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.integrations.admin import OAuthStateSessionAdmin
from apps.integrations.models import OAuthStateSession, oauth_state_service_write
from apps.integrations.oauth_errors import OAuthFlowError
from apps.integrations.oauth_state_service import (
    create_oauth_state,
    consume_oauth_state,
    expire_oauth_states,
    fail_oauth_state,
    oauth_state_digest,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


def oauth_context(code, platform="shopee"):
    tenant = Tenant.objects.create(name=f"Tenant {code}", code=code)
    user = CustomUser.objects.create_user(username=f"user-{code}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    platform_master = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"{platform}-{code}",
        name=f"{platform} demo",
        platform_type=platform,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform_master,
        code=f"store-{code}",
        name=f"Store {code}",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    from apps.integrations.models import PlatformIntegrationConfig

    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform=platform,
        account_alias=f"demo-{code}",
        environment=PlatformIntegrationConfig.Environment.MOCK,
        status=PlatformIntegrationConfig.Status.DISABLED,
        created_by=user,
    )
    return tenant, user, store, config


def start_state(code, platform="shopee", **kwargs):
    tenant, user, store, config = oauth_context(code, platform)
    defaults = dict(
        tenant=tenant,
        platform=platform,
        actor=user,
        integration_config=config,
        store=store,
        region="SG",
        redirect_uri="https://callback.example.test/oauth/return/",
        scopes=["orders.read"],
    )
    defaults.update(kwargs)
    return create_oauth_state(**defaults), tenant, user, store, config


@pytest.mark.django_db
def test_state_create_stores_hash_only_and_consumes_once():
    (plaintext, session), tenant, user, store, config = start_state("state-basic")

    assert plaintext
    assert session.status == OAuthStateSession.Status.PENDING
    assert session.state_hash == oauth_state_digest(plaintext)
    stored_text = " ".join(
        str(getattr(session, field.name)) for field in OAuthStateSession._meta.fields
    )
    assert plaintext not in stored_text
    assert session.initiated_by_id == user.id
    assert session.store_id == store.id
    assert session.integration_config_id == config.id
    assert session.tenant_id == tenant.id

    consumed = consume_oauth_state(plaintext, platform="shopee")
    assert consumed.status == OAuthStateSession.Status.CONSUMED
    assert consumed.consumed_at is not None

    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state(plaintext, platform="shopee")
    assert exc_info.value.controlled_code == "OAUTH_STATE_CONSUMED"


@pytest.mark.django_db
def test_state_expiry_and_cleanup_only_touch_expired_pending():
    from datetime import timedelta

    (plaintext, session), *_ = start_state("state-expiry", ttl=timedelta(seconds=1))
    with oauth_state_service_write():
        OAuthStateSession.objects.filter(pk=session.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state(plaintext, platform="shopee")
    assert exc_info.value.controlled_code == "OAUTH_STATE_EXPIRED"

    (fresh_plaintext, _fresh), *_ = start_state("state-expiry-fresh")
    expired_count = expire_oauth_states()
    assert expired_count == 1
    session.refresh_from_db()
    assert session.status == OAuthStateSession.Status.EXPIRED
    fresh = consume_oauth_state(fresh_plaintext, platform="shopee")
    assert fresh.status == OAuthStateSession.Status.CONSUMED


@pytest.mark.django_db
def test_failed_callback_consumes_state_and_blocks_replay():
    (plaintext, session), *_ = start_state("state-fail")
    consumed = consume_oauth_state(plaintext, platform="shopee")
    failed = fail_oauth_state(consumed, "OAUTH_CALLBACK_REJECTED")
    assert failed.status == OAuthStateSession.Status.FAILED
    assert failed.result_code == "OAUTH_CALLBACK_REJECTED"

    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state(plaintext, platform="shopee")
    assert exc_info.value.controlled_code == "OAUTH_STATE_CONSUMED"


@pytest.mark.django_db
def test_state_platform_and_redirect_validation_fail_session():
    (plaintext, session), *_ = start_state("state-mismatch")
    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state(plaintext, platform="tiktok")
    assert exc_info.value.controlled_code == "OAUTH_PLATFORM_MISMATCH"
    session.refresh_from_db()
    assert session.status == OAuthStateSession.Status.FAILED
    assert session.result_code == "OAUTH_PLATFORM_MISMATCH"

    (plaintext_two, _session_two), *_ = start_state("state-redirect")
    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state(plaintext_two, platform="shopee", redirect_uri="https://evil.example.test/")
    assert exc_info.value.controlled_code == "OAUTH_SESSION_MISMATCH"


@pytest.mark.django_db
def test_tampered_or_missing_state_is_invalid():
    start_state("state-tamper")
    with pytest.raises(OAuthFlowError) as exc_info:
        consume_oauth_state("tampered-state-value", platform="shopee")
    assert exc_info.value.controlled_code == "OAUTH_STATE_INVALID"
    with pytest.raises(OAuthFlowError):
        consume_oauth_state("", platform="shopee")


@pytest.mark.django_db
def test_create_validates_tenant_platform_store_and_redirect():
    tenant, user, store, config = oauth_context("state-validate")
    other_tenant = Tenant.objects.create(name="Other", code="state-validate-other")
    other_user = CustomUser.objects.create_user(
        username="state-validate-other-user", tenant=other_tenant, user_type=CustomUser.UserType.INTERNAL
    )
    base = dict(
        tenant=tenant,
        platform="shopee",
        actor=user,
        integration_config=config,
        store=store,
        region="SG",
        redirect_uri="https://callback.example.test/return/",
        scopes=[],
    )

    with pytest.raises(ValidationError, match="actor"):
        create_oauth_state(**{**base, "actor": other_user})
    with pytest.raises(ValidationError):
        create_oauth_state(**{**base, "platform": "bigseller"})
    with pytest.raises(ValidationError, match="config"):
        create_oauth_state(**{**base, "integration_config": None})
    with pytest.raises(ValidationError, match="store"):
        create_oauth_state(**{**base, "store": None})
    with pytest.raises(ValidationError, match="redirect_uri"):
        create_oauth_state(**{**base, "redirect_uri": "http://insecure.example.test/"})

    cross_platform_master = PlatformMaster.objects.create(
        tenant=tenant, code=f"tiktok-{tenant.code}", name="tiktok demo", platform_type="tiktok"
    )
    cross_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=cross_platform_master,
        code=f"store-cross-{tenant.code}",
        name="Cross store",
        country_code="SG",
        currency="SGD",
        timezone="Asia/Singapore",
    )
    with pytest.raises(ValidationError, match="store platform"):
        create_oauth_state(**{**base, "store": cross_store})


@pytest.mark.django_db
def test_session_binding_is_user_and_state_specific():
    (_, session_a), *_ = start_state("state-binding-a")
    (_, session_b), *_ = start_state("state-binding-b")
    assert session_a.session_binding != session_b.session_binding
    assert len(session_a.session_binding) == 64


@pytest.mark.django_db
def test_state_write_bypasses_are_blocked():
    (_, session), *_ = start_state("state-guard")
    direct = OAuthStateSession(
        tenant=session.tenant,
        platform="shopee",
        initiated_by=session.initiated_by,
        store=session.store,
        integration_config=session.integration_config,
        region="SG",
        state_hash="f" * 64,
        redirect_uri="https://callback.example.test/guard/",
        session_binding="guard",
        expires_at=timezone.now(),
    )
    with pytest.raises(ValidationError, match="service layer"):
        direct.save()
    with pytest.raises(ValidationError, match="service layer"):
        OAuthStateSession.objects.filter(pk=session.pk).update(status="consumed")
    with pytest.raises(ValidationError, match="service layer"):
        OAuthStateSession.objects.bulk_create([direct])
    session.result_code = "changed"
    with pytest.raises(ValidationError, match="service layer"):
        OAuthStateSession.objects.bulk_update([session], ["result_code"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        OAuthStateSession.objects.filter(pk=session.pk).delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        session.delete()

    session.refresh_from_db()
    assert session.status == OAuthStateSession.Status.PENDING
    assert session.result_code == ""
    assert OAuthStateSessionAdmin.has_add_permission(None, None) is False
    assert OAuthStateSessionAdmin.has_change_permission(None, None) is False
    assert OAuthStateSessionAdmin.has_delete_permission(None, None) is False


@pytest.mark.django_db(transaction=True)
def test_concurrent_state_consumption_allows_single_winner():
    if connection.vendor != "mysql":
        pytest.skip("MySQL row-lock verification runs in Local Sandbox.")
    (plaintext, _session), *_ = start_state("state-concurrent")
    start = threading.Event()

    def consume():
        close_old_connections()
        start.wait(timeout=5)
        try:
            consume_oauth_state(plaintext, platform="shopee")
            return "success"
        except OAuthFlowError:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(consume) for _ in range(2)]
        start.set()
        results = [future.result(timeout=15) for future in futures]

    assert sorted(results) == ["conflict", "success"]
