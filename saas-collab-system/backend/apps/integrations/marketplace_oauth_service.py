"""Orchestration for marketplace OAuth start, callback, refresh and revoke.

The service restores the initiating tenant/user from the consumed one-time
state and never trusts request-body tenant or operator values. Only synthetic
provider results are accepted; raw tokens never reach this layer.
"""

from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization

from .credential_service import RAW_CREDENTIAL_FIELDS
from .marketplace_providers import get_oauth_provider
from .models import marketplace_identity_key
from .oauth_errors import OAUTH_CALLBACK_REJECTED, OAUTH_STATE_INVALID, OAUTH_STORE_BOUND_CONFLICT, OAuthFlowError, raise_oauth_error
from .oauth_state_service import consume_oauth_state, create_oauth_state, fail_oauth_state
from .store_authorization_service import (
    create_store_authorization,
    rotate_store_authorization_references,
    transition_store_authorization,
)


def start_marketplace_oauth(*, actor, platform, integration_config, store, region, redirect_uri, scopes):
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
    provider = get_oauth_provider(platform)
    url_payload = provider.build_authorization_url({"state": state_plaintext, "redirect_uri": session.redirect_uri})
    return {
        "platform": platform,
        "authorization_url": url_payload["url"],
        "state": state_plaintext,
        "expires_at": session.expires_at,
    }


def _callback_audit(session, actor, result, result_code, authorization=None):
    IntegrationAuditLog.objects.create(
        tenant=session.tenant,
        integration_config=session.integration_config,
        store_authorization=authorization,
        action="oauth_callback",
        actor=actor,
        result=result,
        masked_detail={"result_code": result_code, "platform": session.platform},
    )


def _apply_exchange_result(session, exchange_result):
    store_record = exchange_result["platform_store_records"][0]
    platform_store_id = store_record["platform_store_id"]
    identity_key = marketplace_identity_key(session.platform, session.region, platform_store_id)
    actor = session.initiated_by
    existing = MarketplaceStoreAuthorization.objects.filter(
        platform=session.platform,
        platform_identity_key=identity_key,
    ).first()
    if existing is not None:
        if existing.tenant_id != session.tenant_id:
            raise_oauth_error(OAUTH_STORE_BOUND_CONFLICT)
        if existing.status == MarketplaceStoreAuthorization.Status.REVOKED:
            raise_oauth_error(OAUTH_STORE_BOUND_CONFLICT, "Revoked authorizations require a new authorization flow.")
        record = rotate_store_authorization_references(
            existing,
            credential_id=exchange_result["credential_id"],
            token_id=exchange_result["token_id"],
            version=existing.credential_reference_version + 1,
            actor=actor,
            expires_at=exchange_result["expires_at"],
        )
        if record.status in {
            MarketplaceStoreAuthorization.Status.PENDING,
            MarketplaceStoreAuthorization.Status.EXPIRED,
            MarketplaceStoreAuthorization.Status.ERROR,
        }:
            record = transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor)
        return record
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
        scopes=exchange_result["authorized_scopes"],
        actor=actor,
    )
    return transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor)


def complete_marketplace_oauth_callback(*, platform, query_params):
    forbidden = RAW_CREDENTIAL_FIELDS.intersection({str(key).lower() for key in query_params})
    state_plaintext = str(query_params.get("state") or "")
    if not state_plaintext:
        raise_oauth_error(OAUTH_STATE_INVALID)
    session = consume_oauth_state(state_plaintext, platform=platform)
    if forbidden:
        fail_oauth_state(session, OAUTH_CALLBACK_REJECTED)
        _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED, OAUTH_CALLBACK_REJECTED)
        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "Callback must not carry raw credential parameters.")
    provider = get_oauth_provider(session.platform)
    context = {"state": state_plaintext, "region": session.region, "scopes": session.requested_scopes}
    try:
        payload = provider.validate_callback(query_params, context)
        payload["scopes"] = session.requested_scopes
        exchange_result = provider.exchange_authorization_code(payload)
        authorization = _apply_exchange_result(session, exchange_result)
    except OAuthFlowError as exc:
        fail_oauth_state(session, exc.controlled_code)
        _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED, exc.controlled_code)
        raise
    _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.SUCCESS, "", authorization=authorization)
    return authorization
