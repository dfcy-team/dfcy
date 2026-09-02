"""Orchestration for marketplace OAuth start, callback, refresh and revoke.

The service restores the initiating tenant/user from the consumed one-time
state and never trusts request-body tenant or operator values. Live providers
return custody references only; raw tokens never reach this layer.
"""

from django.db import transaction

from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization

from .credential_service import RAW_CREDENTIAL_FIELDS
from .marketplace_providers import get_oauth_provider
from .models import marketplace_identity_key

CALLBACK_FORBIDDEN_CONTEXT_FIELDS = {
    "tenant",
    "tenant_id",
    "user",
    "user_id",
    "store",
    "store_id",
    "internal_store_id",
}


def resolve_oauth_provider(platform, integration_config=None):
    """Return the live provider when real-platform mode is fully enabled, else the
    synthetic provider. This keeps ``pending/mock`` behaviour by default and only
    switches to real platforms after the explicit gate checks pass."""
    from .capability import live_network_mode_enabled
    from .live_providers import build_live_provider

    if live_network_mode_enabled():
        return build_live_provider(platform, integration_config=integration_config)
    return get_oauth_provider(platform)
from .oauth_errors import (
    OAUTH_CALLBACK_REJECTED,
    OAUTH_DATABASE_FAILURE,
    OAUTH_STATE_INVALID,
    OAUTH_STORE_BOUND_CONFLICT,
    OAuthFlowError,
    raise_oauth_error,
)
from .oauth_state_service import consume_oauth_state, create_oauth_state, fail_oauth_state
from .store_authorization_service import (
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)


def start_marketplace_oauth(*, actor, platform, integration_config, store, region, redirect_uri, scopes):
    provider = resolve_oauth_provider(platform, integration_config)
    validate_start = getattr(provider, "validate_start_configuration", None)
    if validate_start is not None:
        validate_start(redirect_uri)
    state_plaintext, session = create_oauth_state(
        tenant=actor.tenant,
        platform=platform,
        actor=actor,
        integration_config=integration_config,
        store=store,
        region=region,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )
    provider_context = {
        "state": state_plaintext,
        "redirect_uri": session.redirect_uri,
        "store_code": store.code,
    }
    url_payload = provider.build_authorization_url(provider_context)
    result = {
        "platform": platform,
        "authorization_url": url_payload["url"],
        "expires_at": session.expires_at,
    }
    from .capability import live_network_mode_enabled

    if not live_network_mode_enabled():
        result["state"] = state_plaintext
        result["simulation_callback"] = provider.build_simulation_callback(provider_context)
    return result


def _callback_audit(session, actor, result, result_code, authorization=None):
    IntegrationAuditLog.objects.create(
        tenant=session.tenant,
        integration_config=session.integration_config,
        store_authorization=authorization,
        action="oauth_callback",
        actor=actor,
        result=result,
        masked_detail={
            "result_code": result_code,
            "platform": session.platform,
            "store_id": str(session.store_id),
        },
    )


def _apply_exchange_result(session, exchange_result):
    store_record = exchange_result["platform_store_records"][0]
    platform_store_id = store_record["platform_store_id"]
    identity_key = marketplace_identity_key(session.platform, session.region, platform_store_id)
    actor = session.initiated_by
    existing = MarketplaceStoreAuthorization.objects.filter(
        active_platform_identity_key=identity_key,
    ).first()
    if existing is not None:
        if existing.tenant_id != session.tenant_id:
            raise_oauth_error(OAUTH_STORE_BOUND_CONFLICT)
        record = rotate_store_authorization_references(
            existing,
            credential_id=exchange_result["credential_id"],
            token_id=exchange_result["token_id"],
            version=existing.credential_reference_version + 1,
            actor=actor,
            expires_at=exchange_result["expires_at"],
            credential_mask=exchange_result.get("credential_mask"),
            allow_live_references=exchange_result.get("reference_kind") == "custody",
            revoker=exchange_result.get("previous_reference_revoker"),
            new_reference_revoker=exchange_result.get("new_reference_revoker"),
        )
        if record.status in {
            MarketplaceStoreAuthorization.Status.PENDING,
            MarketplaceStoreAuthorization.Status.EXPIRED,
            MarketplaceStoreAuthorization.Status.ERROR,
        }:
            record = transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor)
        return record
    return _create_authorization_from_exchange(session, exchange_result, store_record)


@transaction.atomic
def _create_authorization_from_exchange(session, exchange_result, store_record):
    actor = session.initiated_by
    platform_store_id = store_record["platform_store_id"]
    record = create_store_authorization(
        tenant=session.tenant,
        integration_config=session.integration_config,
        store=session.store,
        platform=session.platform,
        region=session.region,
        platform_store_id=platform_store_id,
        merchant_subject_id=exchange_result["platform_subject"],
        shop_cipher=store_record.get("shop_cipher", ""),
        credential_id=exchange_result["credential_id"],
        token_id=exchange_result["token_id"],
        credential_mask=exchange_result.get("credential_mask"),
        allow_live_references=exchange_result.get("reference_kind") == "custody",
        scopes=exchange_result["authorized_scopes"],
        actor=actor,
    )
    return transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor)


def _revoke_uncommitted_exchange(exchange_result):
    revoker = exchange_result.get("new_reference_revoker") if isinstance(exchange_result, dict) else None
    if revoker is None:
        return
    try:
        revoker(exchange_result.get("credential_id"), exchange_result.get("token_id"))
    except Exception:
        return


def complete_marketplace_oauth_callback(*, platform, query_params):
    callback_keys = {str(key).lower() for key in query_params}
    forbidden = (RAW_CREDENTIAL_FIELDS | CALLBACK_FORBIDDEN_CONTEXT_FIELDS).intersection(callback_keys)
    state_plaintext = str(query_params.get("state") or "")
    if not state_plaintext:
        raise_oauth_error(OAUTH_STATE_INVALID)
    session = consume_oauth_state(state_plaintext, platform=platform)
    if forbidden:
        fail_oauth_state(session, OAUTH_CALLBACK_REJECTED)
        _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED, OAUTH_CALLBACK_REJECTED)
        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "Callback must not carry raw credential parameters.")
    provider = resolve_oauth_provider(session.platform, session.integration_config)
    context = {"state": state_plaintext, "region": session.region, "scopes": session.requested_scopes}
    try:
        payload = provider.validate_callback(query_params, context)
        payload["scopes"] = session.requested_scopes
        exchange_result = provider.exchange_authorization_code(payload)
        try:
            authorization = _apply_exchange_result(session, exchange_result)
        except OAuthFlowError:
            _revoke_uncommitted_exchange(exchange_result)
            raise
        except Exception:
            _revoke_uncommitted_exchange(exchange_result)
            raise_oauth_error(OAUTH_DATABASE_FAILURE, "Authorization persistence failed.")
    except OAuthFlowError as exc:
        fail_oauth_state(session, exc.controlled_code)
        _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED, exc.controlled_code)
        raise
    _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.SUCCESS, "", authorization=authorization)
    return authorization


def refresh_marketplace_authorization(record, *, actor):
    provider = resolve_oauth_provider(record.platform, record.integration_config)
    result = provider.refresh_authorization(record)
    return rotate_store_authorization_references(
        record,
        credential_id=result["credential_id"],
        token_id=result["token_id"],
        version=result["reference_version"],
        actor=actor,
        expires_at=result["expires_at"],
        credential_mask=result.get("credential_mask"),
        allow_live_references=result.get("reference_kind") == "custody",
        revoker=result.get("previous_reference_revoker"),
        new_reference_revoker=result.get("new_reference_revoker"),
    )


def revoke_marketplace_authorization(record, *, actor):
    if record.status == MarketplaceStoreAuthorization.Status.REVOKED:
        IntegrationAuditLog.objects.create(
            tenant=record.tenant,
            integration_config=record.integration_config,
            store_authorization=record,
            action="revoke",
            actor=actor,
            result=IntegrationAuditLog.Result.SUCCESS,
            masked_detail={"idempotent": True, "status": record.status},
        )
        return record, True
    provider = resolve_oauth_provider(record.platform, record.integration_config)
    outcome = provider.revoke_authorization(record)
    if outcome.get("status") != "revoked":
        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "Provider revoke did not confirm revocation.")
    revoked = transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.REVOKED, actor=actor)
    return revoked, False
