"""Disposable SQLite + synthetic recovery fixture; no live OAuth or custody."""
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlsplit

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.integrations import tiktok_shop_binding as binding
from apps.integrations.models import (TikTokShopBindingSession as Binding, OAuthStateSession,
    MarketplaceStoreAuthorization, shop_binding_service_write, oauth_state_service_write)
from apps.integrations.oauth_errors import OAuthFlowError
from tests.test_tiktok_manual_callback_recovery import recovery
from tests.test_marketplace_callback_acceptance import marketplace_callback
from tests.test_lazada_store_authorization import lazada_context

pytestmark = [pytest.mark.django_db(transaction=True),
              pytest.mark.parametrize("marketplace_callback", ["tiktok"], indirect=True)]


@pytest.fixture
def context(recovery, monkeypatch):
    client, store, config, payload, exchange, result, cleanup, provider = recovery
    store.external_store_id = ""
    store.save(update_fields=["external_store_id"])
    actor = client.handler._force_user
    params = dict(parse_qsl(urlsplit(payload["callback_url"]).query))
    params["state"] = payload["tiktok_pending_token"]
    provider.custody.revoke.return_value = {"status": "revoked"}
    provider.custody.lookup_reference_by_operation.return_value = {"found": False}
    monkeypatch.setattr(binding, "get_custody_backend", lambda: provider.custody)
    return actor, store, config, params, exchange, result, provider


def start(context):
    actor, _, _, params, _, _, _ = context
    return binding.start_shop_binding(actor=actor, query_params=params, callback_state_verified=True)


def test_discover_confirm_safe_idempotent_and_consumed_expiry(context):
    actor, store, _, params, exchange, result, _ = context
    def durable(payload):
        row = Binding.objects.get()
        assert not transaction.get_connection().in_atomic_block
        assert row.status == "exchanging"
        assert payload["custody_operation_id"] == str(row.operation_id)
        assert payload["discover_shop_binding"] is True
        assert OAuthStateSession.objects.get().status == "consumed"
        return result
    exchange.side_effect = durable
    pending = start(context)
    assert pending["status"] == "pending_confirmation"
    assert "shop_cipher" not in str(pending)
    assert result["token_id"] not in str(pending)
    assert binding.get_binding(actor, pending["binding_id"]) == pending
    with pytest.raises(OAuthFlowError):
        start(context)
    assert exchange.call_count == 1
    with oauth_state_service_write():
        OAuthStateSession.objects.update(expires_at=timezone.now() - timedelta(days=1))
    sid = pending["candidates"][0]["platform_store_id"]
    bound = binding.confirm_shop_binding(actor, pending["binding_id"], sid)
    assert bound["status"] == "bound"
    assert "token_id" not in str(bound) and "credential_id" not in str(bound)
    assert binding.confirm_shop_binding(actor=actor, binding_id=pending["binding_id"], platform_store_id=sid) == bound
    with pytest.raises(OAuthFlowError):
        binding.confirm_shop_binding(actor, pending["binding_id"], "FAKE_OTHER")
    store.refresh_from_db()
    assert store.external_store_id == sid
    assert store.external_store_identity_key
    assert MarketplaceStoreAuthorization.objects.count() == 1


@pytest.mark.parametrize("case", ["unverified", "bound", "inactive", "external", "tenant", "country", "config", "scope", "tenant_status", "platform_status", "platform_tenant"])
def test_start_rejections_do_not_exchange_or_consume(context, case, monkeypatch):
    actor, store, config, params, exchange, _, _ = context
    if case == "bound":
        store.external_store_id = "FAKE_BOUND"
        store.save()
    elif case == "inactive":
        type(actor).objects.filter(pk=actor.pk).update(is_active=False)
    elif case == "external":
        type(actor).objects.filter(pk=actor.pk).update(user_type="external")
    elif case == "tenant":
        from apps.tenants.models import Tenant
        tenant = Tenant.objects.create(name="Other", code="other")
        type(actor).objects.filter(pk=actor.pk).update(tenant=tenant)
    elif case == "country":
        store.country_code = "PH"
        store.save()
    elif case == "config":
        config.scopes = ["FAKE_CHANGED"]
        config.save()
    elif case == "scope":
        monkeypatch.setattr(binding.oauth, "integration_values_allowed", lambda *a, **kw: False)
    elif case == "tenant_status":
        type(actor.tenant).objects.filter(pk=actor.tenant_id).update(status="suspended")
    elif case == "platform_status":
        type(store.platform).objects.filter(pk=store.platform_id).update(status="inactive")
    elif case == "platform_tenant":
        from apps.tenants.models import Tenant
        tenant = Tenant.objects.create(name="Other platform", code="other-platform")
        type(store.platform).objects.filter(pk=store.platform_id).update(tenant=tenant)
    with pytest.raises(OAuthFlowError):
        binding.start_shop_binding(actor, params, callback_state_verified=case != "unverified")
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"


@pytest.mark.parametrize("case", ["country", "duplicate", "expired", "id", "cipher", "subject", "scopes"])
def test_invalid_discovery_keeps_cleanup_evidence(context, case):
    _, _, _, _, _, result, _ = context
    if case == "country":
        result["platform_store_records"][0]["region"] = "PH"
    elif case == "duplicate":
        result["platform_store_records"] *= 2
    elif case == "expired":
        result["expires_at"] = timezone.now() - timedelta(seconds=1)
    elif case == "id":
        result["platform_store_records"][0]["platform_store_id"] = "invalid/shop"
    elif case == "cipher":
        result["platform_store_records"][0]["shop_cipher"] = ""
    elif case == "subject":
        result["platform_subject"] = ""
    elif case == "scopes":
        result["authorized_scopes"] = "not-a-list"
    with pytest.raises(OAuthFlowError):
        start(context)
    row = Binding.objects.get()
    assert row.status == "cleanup_pending"
    assert row.exchange_data["token_id"] == result["token_id"]
    assert binding.cleanup_shop_bindings()["cleaned"] == 1


@pytest.mark.parametrize("case", ["config", "store", "expired", "candidate", "inactive", "scope"])
def test_confirmation_revalidates(context, case, monkeypatch):
    actor, store, config, _, _, _, _ = context
    pending = start(context)
    sid = pending["candidates"][0]["platform_store_id"]
    if case == "config":
        config.scopes = ["FAKE_MUTATED"]
        config.save()
    elif case == "store":
        store.country_code = "PH"
        store.save()
    elif case == "expired":
        with shop_binding_service_write():
            Binding.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    elif case == "candidate":
        sid = "FAKE_OTHER"
    elif case == "inactive":
        type(actor).objects.filter(pk=actor.pk).update(is_active=False)
    else:
        monkeypatch.setattr(binding.oauth, "integration_values_allowed", lambda *a, **kw: False)
    with pytest.raises(OAuthFlowError):
        binding.confirm_shop_binding(actor, pending["binding_id"], sid)
    assert not MarketplaceStoreAuthorization.objects.exists()


def test_tenant_and_user_cannot_read_confirm_cancel(context):
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    pending = start(context)
    actor, store, *_ = context
    tenant = Tenant.objects.create(name="Other", code="other")
    for owner in (store.tenant, tenant):
        other = CustomUser.objects.create_user(username=f"other-{owner.pk}", tenant=owner, is_superuser=True, user_type="internal")
        for fn, args in ((binding.get_binding, ()), (binding.cancel_shop_binding, ()),
                         (binding.confirm_shop_binding, (pending["candidates"][0]["platform_store_id"],))):
            with pytest.raises(OAuthFlowError):
                fn(other, pending["binding_id"], *args)


def test_confirmation_audit_failure_rolls_back_identity_and_authorization(context, monkeypatch):
    actor, store, *_ = context
    pending = start(context)
    monkeypatch.setattr(binding.oauth, "_callback_audit", Mock(side_effect=RuntimeError("synthetic")))
    with pytest.raises(RuntimeError):
        binding.confirm_shop_binding(actor, pending["binding_id"], pending["candidates"][0]["platform_store_id"])
    store.refresh_from_db()
    assert store.external_store_id == ""
    assert not MarketplaceStoreAuthorization.objects.exists()
    assert Binding.objects.get().status == "pending_confirmation"


def test_uniqueness_failure_rolls_back(context):
    actor, store, *_ = context
    pending = start(context)
    sid = pending["candidates"][0]["platform_store_id"]
    Store = type(store)
    Store.objects.create(tenant=store.tenant, platform=store.platform, code="other-shop", name="Other",
                         country_code=store.country_code, currency="MYR", external_store_id=sid)
    with pytest.raises((IntegrityError, ValidationError)):
        binding.confirm_shop_binding(actor, pending["binding_id"], sid)
    store.refresh_from_db()
    assert store.external_store_id == ""
    assert not MarketplaceStoreAuthorization.objects.exists()


def test_cleanup_retry_and_any_status_ownership(context):
    actor, _, _, _, _, _, provider = context
    pending = start(context)
    binding.cancel_shop_binding(actor=actor, binding_id=pending["binding_id"])
    provider.custody.revoke.side_effect = RuntimeError("FAKE_SECRET_DO_NOT_PERSIST")
    assert binding.cleanup_shop_bindings()["retry"] == 1
    row = Binding.objects.get()
    assert row.cleanup_attempts == 1 and "FAKE_SECRET" not in row.cleanup_error
    provider.custody.revoke.side_effect = None
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    assert binding.cleanup_shop_bindings()["claimed"] == 0


@pytest.mark.parametrize("status", ["active", "revoked", "expired", "error"])
def test_cleanup_never_revokes_authorization_owned_refs(context, status):
    actor, _, _, _, _, _, provider = context
    pending = start(context)
    binding.confirm_shop_binding(actor, pending["binding_id"], pending["candidates"][0]["platform_store_id"])
    from apps.integrations.models import authorization_service_write
    with authorization_service_write():
        MarketplaceStoreAuthorization.objects.update(status=status)
    # Simulate recovery of a legacy cancelled staging row sharing committed refs.
    with shop_binding_service_write():
        Binding.objects.update(status="cancelled")
    assert binding.cleanup_shop_bindings()["owned"] == 1
    provider.custody.revoke.assert_not_called()


def test_stale_exchange_lookup_and_fencing(context):
    actor, _, _, _, exchange, _, provider = context
    exchange.side_effect = RuntimeError("FAKE_NO_CODE_RETRY")
    with pytest.raises(OAuthFlowError):
        start(context)
    provider.custody.lookup_reference_by_operation.side_effect = RuntimeError("unavailable")
    assert binding.cleanup_shop_bindings()["retry"] == 1
    provider.custody.lookup_reference_by_operation.side_effect = None
    provider.custody.lookup_reference_by_operation.return_value = {
        "found": True, "credential_id": "FAKE_CRASH_CREDENTIAL", "token_id": "FAKE_CRASH_TOKEN", "status": "active"}
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    assert exchange.call_count == 1
    assert Binding.objects.get().cleanup_attempts == 2
    provider.custody.lookup_reference_by_operation.assert_called_with(str(Binding.objects.get().pk), close=True)


def test_closed_absence_safely_finishes_uncertain_exchange(context):
    _, _, _, _, exchange, _, provider = context
    exchange.side_effect = RuntimeError("synthetic")
    with pytest.raises(OAuthFlowError):
        start(context)
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    provider.custody.revoke.assert_not_called()


def test_stale_exchange_active_window_and_permanent_close(context):
    _, _, _, _, exchange, _, provider = context
    exchange.side_effect = RuntimeError("synthetic")
    with pytest.raises(OAuthFlowError):
        start(context)
    with shop_binding_service_write():
        Binding.objects.update(status="exchanging")
    assert binding.cleanup_shop_bindings()["claimed"] == 0
    with shop_binding_service_write():
        Binding.objects.update(updated_at=timezone.now() - timedelta(minutes=3))
    assert binding.cleanup_shop_bindings(limit=1000)["cleaned"] == 1
    provider.custody.lookup_reference_by_operation.assert_called_once_with(str(Binding.objects.get().pk), close=True)
    assert exchange.call_count == 1


def test_cleanup_worker_losing_fence_cannot_revoke_or_finish(context):
    actor, _, _, _, _, _, provider = context
    pending = start(context)
    binding.cancel_shop_binding(actor, pending["binding_id"])
    def lose_claim(*args, **kwargs):
        with shop_binding_service_write():
            Binding.objects.update(cleanup_fence=__import__("uuid").uuid4())
        return {"found": False}
    provider.custody.lookup_reference_by_operation.side_effect = lose_claim
    assert binding.cleanup_shop_bindings()["cleaned"] == 0
    assert Binding.objects.get().status == "cleaning"
    provider.custody.revoke.assert_not_called()


def test_cleanup_claim_during_exchange_cannot_promote_late_result(context):
    _, _, _, _, exchange, result, provider = context
    def late(payload):
        with shop_binding_service_write():
            Binding.objects.update(updated_at=timezone.now() - timedelta(minutes=3))
        assert binding.cleanup_shop_bindings()["cleaned"] == 1
        return result
    exchange.side_effect = late
    with pytest.raises(OAuthFlowError):
        start(context)
    assert Binding.objects.get().status == "cleaned"
    assert not MarketplaceStoreAuthorization.objects.exists()


def test_binding_ttl_is_capped_by_token_expiry(context):
    _, _, _, _, _, result, _ = context
    result["expires_at"] = timezone.now() + timedelta(minutes=3)
    assert start(context)["expires_at"] == result["expires_at"]


def test_shop_binding_migration_applies_to_disposable_sqlite(context):
    """Exercise only the additive migration; never replay unrelated historical SQL."""
    import importlib
    from django.apps import apps
    from django.db import connection, connections
    from django.db.backends.sqlite3.base import DatabaseWrapper
    from django.db.migrations.state import ProjectState
    state = ProjectState.from_apps(apps)
    state.remove_model("integrations", "tiktokshopbindingsession")
    for model in ("oauthstatesession", "adsoauthsession"):
        state.remove_field("integrations", model, "browser_verifier_hash")
        state.remove_field("integrations", model, "callback_transport")
    settings = {**connection.settings_dict, "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:", "OPTIONS": {}}
    isolated = DatabaseWrapper(settings, alias="binding_migration_synthetic")
    connections[isolated.alias] = isolated
    try:
        with isolated.schema_editor() as editor:
            for model in ("OAuthStateSession", "AdsOAuthSession"):
                editor.create_model(state.apps.get_model("integrations", model))
        module = importlib.import_module("apps.integrations.migrations.0050_tiktok_shop_binding")
        migration = module.Migration("0050_tiktok_shop_binding", "integrations")
        with isolated.schema_editor() as editor:
            migration.apply(state, editor)
        with isolated.cursor() as cursor:
            tables = isolated.introspection.table_names(cursor)
            assert "integrations_tiktokshopbindingsession" in tables
            for table in ("integrations_oauthstatesession", "integrations_adsoauthsession"):
                names = {column.name for column in isolated.introspection.get_table_description(cursor, table)}
                assert {"browser_verifier_hash", "callback_transport"} <= names
    finally:
        isolated.close()
        del connections[isolated.alias]


def test_model_guards_and_one_to_one(context):
    start(context)
    row = Binding.objects.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        Binding.objects.update(status="bound")
    with pytest.raises(ValidationError):
        Binding.objects.bulk_update([row], ["status"])
    with pytest.raises(ValidationError):
        Binding.objects.bulk_create([row])
    with pytest.raises(ValidationError):
        Binding.objects.all().delete()
    with pytest.raises(ValidationError):
        row.delete()
    row.pk = None
    row.operation_id = __import__("uuid").uuid4()
    with pytest.raises(IntegrityError), shop_binding_service_write(), transaction.atomic():
        row.save(force_insert=True)


@pytest.fixture
def known_context(context):
    actor, store, _, _, _, result, _ = context
    sid = result["platform_store_records"][0]["platform_store_id"]
    store.external_store_id = sid
    store.save(update_fields=["external_store_id"])
    session = OAuthStateSession.objects.get()
    session.store = store
    authorization = binding.oauth._create_authorization_from_exchange(session, result,
                                                                      result["platform_store_records"][0])
    with oauth_state_service_write():
        OAuthStateSession.objects.update(callback_transport="direct", browser_verifier_hash="a" * 64)
    # Exercise the live-reference rotation branch without a live provider or network.
    result.update(credential_id="FAKE_NEW_CREDENTIAL", token_id="FAKE_NEW_TOKEN", reference_kind="custody",
                  credential_mask={"credential": "FAKE_MUST_BE_MASKED", "token": "FAKE_MUST_BE_MASKED"})
    return context, authorization, sid


@pytest.mark.parametrize("state_verified", [True, False])
def test_known_shop_auto_rotates_exact_authorization_once(known_context, state_verified):
    context, authorization, sid = known_context
    actor, _, _, params, exchange, result, provider = context
    original_id = authorization.pk
    old_refs = (authorization.credential_id, authorization.token_id)
    bound = binding.complete_bound_shop_authorization(actor=actor, query_params=params,
        expected_store_id=sid, callback_state_verified=state_verified)
    row = Binding.objects.get()
    assert row.operation_id == row.pk and row.store_identity["external_store_id"] == sid
    assert bound["status"] == "bound" and bound["authorization_id"] == original_id
    assert MarketplaceStoreAuthorization.objects.count() == 1
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 2
    assert authorization.token_id == result["token_id"]
    assert authorization.credential_mask == {"credential": "********", "token": "********"}
    assert exchange.call_args.args[0]["target_shop_id"] == sid
    assert "discover_shop_binding" not in exchange.call_args.args[0]
    provider.custody.revoke.assert_called_once_with(*old_refs)
    assert binding.confirm_shop_binding(actor, row.pk, sid) == bound
    with pytest.raises(OAuthFlowError):
        binding.complete_bound_shop_authorization(actor, params, sid, state_verified)
    assert exchange.call_count == 1
    assert "FAKE_MUST_BE_MASKED" not in str(row.exchange_data)


@pytest.mark.parametrize("case", ["wrong_target", "missing_proof", "wrong_transport"])
def test_known_shop_unverified_path_requires_direct_proof(known_context, case):
    context, _, sid = known_context
    actor, _, _, params, exchange, _, _ = context
    if case == "wrong_target":
        sid = "FAKE_WRONG_TARGET"
    else:
        with oauth_state_service_write():
            OAuthStateSession.objects.update(**({"browser_verifier_hash": ""} if case == "missing_proof"
                                                else {"callback_transport": "legacy"}))
    with pytest.raises(OAuthFlowError):
        binding.complete_bound_shop_authorization(actor, params, sid, False)
    exchange.assert_not_called()
    assert OAuthStateSession.objects.get().status == "pending"
    assert not Binding.objects.exists()


def test_known_target_cannot_rotate_unrelated_config(known_context):
    context, authorization, sid = known_context
    actor, _, config, params, _, _, provider = context
    # A valid but different config already owns this active platform identity.
    from apps.integrations.models import PlatformIntegrationConfig, authorization_service_write
    other = PlatformIntegrationConfig.objects.create(tenant=config.tenant, platform="tiktok", account_alias="other",
        environment=config.environment, status="verified", regions=config.regions, contract_version=config.contract_version,
        callback_url=config.callback_url, scopes=[], platform_config=config.platform_config, created_by=actor)
    with authorization_service_write():
        MarketplaceStoreAuthorization.objects.filter(pk=authorization.pk).update(integration_config=other)
    old_refs = (authorization.credential_id, authorization.token_id)
    with pytest.raises(OAuthFlowError) as caught:
        binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert "other" not in str(caught.value)
    assert Binding.objects.get().status == "cleanup_pending"
    authorization.refresh_from_db()
    assert (authorization.credential_id, authorization.token_id) == old_refs
    assert MarketplaceStoreAuthorization.objects.count() == 1
    provider.custody.revoke.assert_not_called()


def test_known_rotation_audit_rollback_keeps_operation_for_cleanup(known_context, monkeypatch):
    context, authorization, sid = known_context
    actor, store, _, params, _, result, provider = context
    old_refs = (authorization.credential_id, authorization.token_id)
    monkeypatch.setattr(binding.oauth, "_callback_audit", Mock(side_effect=RuntimeError("FAKE_SECRET")))
    with pytest.raises(OAuthFlowError) as caught:
        binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert "FAKE_SECRET" not in str(caught.value)
    row = Binding.objects.get()
    assert row.status == "cleanup_pending" and row.exchange_data["token_id"] == result["token_id"]
    assert "previous_reference" not in row.exchange_data  # Rolled back with the rotation.
    authorization.refresh_from_db()
    store.refresh_from_db()
    assert store.external_store_id == sid
    assert (authorization.credential_id, authorization.token_id) == old_refs
    provider.custody.revoke.assert_not_called()
    provider.custody.revoke.side_effect = RuntimeError("FAKE_REVOCATION_SECRET")
    assert binding.cleanup_shop_bindings()["retry"] == 1
    provider.custody.revoke.side_effect = None
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    assert all(call.args != old_refs for call in provider.custody.revoke.call_args_list)


def test_known_crash_after_custody_store_has_durable_operation(known_context):
    context, authorization, sid = known_context
    actor, _, _, params, exchange, result, provider = context
    def crash(payload):
        assert payload["custody_operation_id"] == str(Binding.objects.get().pk)
        raise SystemExit("synthetic process death after custody store")
    exchange.side_effect = crash
    with pytest.raises(SystemExit):
        binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert Binding.objects.get().status == "exchanging"
    provider.custody.lookup_reference_by_operation.return_value = {
        "found": True, "credential_id": result["credential_id"], "token_id": result["token_id"], "status": "active"}
    with shop_binding_service_write():
        Binding.objects.update(updated_at=timezone.now() - timedelta(minutes=3))
    provider.custody.revoke.side_effect = RuntimeError("synthetic unavailable")
    assert binding.cleanup_shop_bindings()["retry"] == 1
    provider.custody.revoke.side_effect = None
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 1
    assert authorization.token_id != result["token_id"]
    assert exchange.call_count == 1


def test_known_committed_rotation_never_cleans_owned_new_refs(known_context):
    context, authorization, sid = known_context
    actor, _, _, params, _, result, provider = context
    # Existing rotation service records failed old-reference cleanup after commit.
    provider.custody.revoke.side_effect = RuntimeError("synthetic previous revoke failure")
    bound = binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert bound["status"] == "bound"
    authorization.refresh_from_db()
    assert authorization.token_id == result["token_id"]
    with shop_binding_service_write():
        Binding.objects.update(status="cleanup_pending")
    assert binding.cleanup_shop_bindings()["owned"] == 1
    assert all(call.args != (result["credential_id"], result["token_id"])
               for call in provider.custody.revoke.call_args_list)


def test_known_store_without_authorization_creates_exact_one(context):
    actor, store, _, params, exchange, result, _ = context
    sid = result["platform_store_records"][0]["platform_store_id"]
    store.external_store_id = sid
    store.save(update_fields=["external_store_id"])
    bound = binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert bound["status"] == "bound"
    assert MarketplaceStoreAuthorization.objects.count() == 1
    assert exchange.call_args.args[0]["target_shop_id"] == sid


@pytest.mark.parametrize("case", ["changed_identity", "different_shop", "multiple_shops"])
def test_known_exchange_must_remain_exact_target(known_context, case):
    context, authorization, sid = known_context
    actor, store, _, params, exchange, result, provider = context
    def invalid(payload):
        if case == "changed_identity":
            type(store).objects.filter(pk=store.pk).update(external_store_id="FAKE_CHANGED")
        elif case == "different_shop":
            result["platform_store_records"][0]["platform_store_id"] = "FAKE_OTHER"
        else:
            result["platform_store_records"].append({**result["platform_store_records"][0],
                                                    "platform_store_id": "FAKE_OTHER"})
        return result
    exchange.side_effect = invalid
    with pytest.raises(OAuthFlowError):
        binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert Binding.objects.get().status == "cleanup_pending"
    authorization.refresh_from_db()
    assert authorization.credential_reference_version == 1
    assert authorization.token_id != result["token_id"]
    provider.custody.revoke.assert_not_called()


def test_cleanup_is_independent_of_platform_provider_mode_and_config(context, monkeypatch, settings):
    actor, _, config, _, _, result, provider = context
    pending = start(context)
    binding.cancel_shop_binding(actor, pending["binding_id"])
    settings.PLATFORM_NETWORK_MODE = "mock"
    settings.LIVE_PLATFORM_SECURITY_APPROVED = False
    config.status = "disabled"
    config.platform_config = {"api_type": "advertising"}
    config.save()
    resolver = Mock(side_effect=AssertionError("Cleanup must not build a platform provider"))
    monkeypatch.setattr(binding.oauth, "resolve_oauth_provider", resolver)
    assert binding.cleanup_shop_bindings()["cleaned"] == 1
    resolver.assert_not_called()
    provider.custody.lookup_reference_by_operation.assert_called_once_with(pending["binding_id"], close=True)
    provider.custody.revoke.assert_called_once_with(result["credential_id"], result["token_id"])


def test_unavailable_custody_factory_keeps_cleanup_retryable(context, monkeypatch):
    actor, _, _, _, _, _, provider = context
    pending = start(context)
    binding.cancel_shop_binding(actor, pending["binding_id"])
    monkeypatch.setattr(binding, "get_custody_backend", Mock(side_effect=RuntimeError("FAKE_BACKEND_SECRET")))
    assert binding.cleanup_shop_bindings()["retry"] == 1
    row = Binding.objects.get()
    assert row.status == "cleanup_pending" and row.cleanup_attempts == 1
    assert "FAKE_BACKEND_SECRET" not in row.cleanup_error
    provider.custody.revoke.assert_not_called()


def test_previous_live_reference_outbox_retries_failed_on_commit(known_context):
    context, authorization, sid = known_context
    actor, _, _, params, _, result, provider = context
    old_refs = (authorization.credential_id, authorization.token_id)
    def failed_commit_revoke(*args):
        row = Binding.objects.get()
        assert not transaction.get_connection().in_atomic_block
        assert row.status == "bound"
        assert row.exchange_data["previous_reference_cleanup"] == "pending"
        assert args == old_refs
        raise RuntimeError("FAKE_PREVIOUS_SECRET")
    provider.custody.revoke.side_effect = failed_commit_revoke
    binding.complete_bound_shop_authorization(actor, params, sid, True)
    provider.custody.revoke.side_effect = RuntimeError("FAKE_PREVIOUS_SECRET")
    assert binding.cleanup_previous_shop_references()["retry"] == 1
    row = Binding.objects.get()
    assert row.status == "bound"
    assert row.exchange_data["previous_reference_cleanup"] == "pending"
    assert row.exchange_data["previous_reference_cleanup_attempts"] == 1
    assert "FAKE_PREVIOUS_SECRET" not in row.exchange_data["previous_reference_cleanup_error"]
    provider.custody.revoke.side_effect = None
    assert binding.cleanup_previous_shop_references()["cleaned"] == 1
    row.refresh_from_db()
    authorization.refresh_from_db()
    assert row.status == "bound" and row.exchange_data["previous_reference_cleanup"] == "cleaned"
    assert authorization.token_id == result["token_id"]
    assert binding.cleanup_previous_shop_references()["claimed"] == 0
    assert all(call.args == old_refs for call in provider.custody.revoke.call_args_list)
    provider.custody.lookup_reference_by_operation.assert_not_called()


@pytest.mark.parametrize("owned_field", ["credential_id", "token_id"])
def test_previous_reference_outbox_checks_any_authorization_even_revoked(known_context, owned_field):
    context, authorization, sid = known_context
    actor, _, _, params, _, result, provider = context
    old_refs = {"credential_id": authorization.credential_id, "token_id": authorization.token_id}
    binding.complete_bound_shop_authorization(actor, params, sid, True)
    authorization.refresh_from_db()
    from apps.integrations.models import authorization_service_write, marketplace_identity_key
    owner_data = MarketplaceStoreAuthorization.objects.filter(pk=authorization.pk).values().get()
    owner_data.pop("id")
    owner_data.update(status="revoked", active_platform_identity_key=None, active_store_binding_key=None,
        platform_store_id="FAKE_HISTORICAL_OWNER", credential_id="FAKE_OWNER_CREDENTIAL", token_id="FAKE_OWNER_TOKEN")
    owner_data["platform_identity_key"] = marketplace_identity_key("tiktok", authorization.region, "FAKE_HISTORICAL_OWNER")
    owner_data[owned_field] = old_refs[owned_field]
    with authorization_service_write():
        MarketplaceStoreAuthorization.objects.create(**owner_data)
    provider.custody.revoke.reset_mock()
    assert binding.cleanup_previous_shop_references()["owned"] == 1
    row = Binding.objects.get()
    assert row.status == "bound" and row.exchange_data["previous_reference_cleanup"] == "owned"
    authorization.refresh_from_db()
    assert authorization.token_id == result["token_id"]
    provider.custody.revoke.assert_not_called()
    provider.custody.lookup_reference_by_operation.assert_not_called()


def test_previous_reference_outbox_survives_lost_on_commit_and_lease(known_context, monkeypatch):
    context, authorization, sid = known_context
    actor, _, _, params, _, result, provider = context
    old_refs = (authorization.credential_id, authorization.token_id)
    callbacks = []
    monkeypatch.setattr(binding.transaction, "on_commit", lambda callback, **kw: callbacks.append(callback))
    binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert callbacks  # Simulate process exit before these callbacks execute.
    provider.custody.revoke.assert_not_called()
    with shop_binding_service_write():
        Binding.objects.update(cleanup_lease_until=timezone.now() + timedelta(minutes=1))
    assert binding.cleanup_previous_shop_references()["claimed"] == 0
    with shop_binding_service_write():
        Binding.objects.update(cleanup_lease_until=timezone.now() - timedelta(seconds=1))
    assert binding.cleanup_previous_shop_references()["cleaned"] == 1
    provider.custody.revoke.assert_called_once_with(*old_refs)
    provider.custody.lookup_reference_by_operation.assert_not_called()
    authorization.refresh_from_db()
    assert authorization.token_id == result["token_id"]


def test_previous_reference_outbox_lost_fence_does_not_acknowledge(known_context):
    context, _, sid = known_context
    actor, _, _, params, _, _, provider = context
    binding.complete_bound_shop_authorization(actor, params, sid, True)
    def lose_fence(*args):
        with shop_binding_service_write():
            Binding.objects.update(cleanup_fence=__import__("uuid").uuid4())
        return {"status": "revoked"}
    provider.custody.revoke.side_effect = lose_fence
    assert binding.cleanup_previous_shop_references()["cleaned"] == 0
    row = Binding.objects.get()
    assert row.status == "bound" and row.exchange_data["previous_reference_cleanup"] == "pending"


def test_previous_reference_cleanup_never_revokes_new_pair(known_context):
    context, _, sid = known_context
    actor, _, _, params, _, result, provider = context
    binding.complete_bound_shop_authorization(actor, params, sid, True)
    row = Binding.objects.get()
    with shop_binding_service_write():
        row.exchange_data["previous_reference"]["credential_id"] = result["credential_id"]
        row.save()
    provider.custody.revoke.reset_mock()
    assert binding.cleanup_previous_shop_references()["owned"] == 1
    provider.custody.revoke.assert_not_called()
    provider.custody.lookup_reference_by_operation.assert_not_called()


@pytest.mark.parametrize("owned_field", ["credential_id", "token_id"])
def test_immediate_previous_revoker_protects_existing_other_owner(known_context, owned_field):
    context, authorization, sid = known_context
    actor, _, _, params, _, result, provider = context
    from apps.integrations.models import authorization_service_write, marketplace_identity_key, IntegrationAuditLog
    owner_data = MarketplaceStoreAuthorization.objects.filter(pk=authorization.pk).values().get()
    owner_data.pop("id")
    old_value = owner_data[owned_field]
    owner_data.update(status="revoked", active_platform_identity_key=None, active_store_binding_key=None,
        platform_store_id="FAKE_IMMEDIATE_OWNER", credential_id="FAKE_OTHER_CREDENTIAL", token_id="FAKE_OTHER_TOKEN")
    owner_data["platform_identity_key"] = marketplace_identity_key("tiktok", authorization.region, "FAKE_IMMEDIATE_OWNER")
    owner_data[owned_field] = old_value
    with authorization_service_write():
        MarketplaceStoreAuthorization.objects.create(**owner_data)
    bound = binding.complete_bound_shop_authorization(actor, params, sid, True)
    assert bound["status"] == "bound"
    authorization.refresh_from_db()
    assert authorization.token_id == result["token_id"]
    provider.custody.revoke.assert_not_called()
    row = Binding.objects.get()
    assert row.exchange_data["previous_reference_cleanup"] == "pending"
    audit = IntegrationAuditLog.objects.filter(action="oauth_previous_reference_cleanup").latest("pk")
    assert audit.masked_detail["revocation"] == {"status": "failed", "error_code": "REFERENCES_OWNED"}
    assert binding.cleanup_previous_shop_references()["owned"] == 1
    provider.custody.revoke.assert_not_called()
    provider.custody.lookup_reference_by_operation.assert_not_called()
