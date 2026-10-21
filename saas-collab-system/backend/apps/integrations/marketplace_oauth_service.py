"""Orchestration for marketplace OAuth start, callback, refresh and revoke.

The service restores the initiating tenant/user from the consumed one-time
state and never trusts request-body tenant or operator values. Live providers
return custody references only; raw tokens never reach this layer.
"""

from django.db import transaction
from rest_framework.exceptions import APIException

from apps.accounts.models import CustomUser
from apps.integrations.models import IntegrationAuditLog, MarketplaceStoreAuthorization
from apps.permissions.services import user_has_integration_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .credential_service import RAW_CREDENTIAL_FIELDS
from .marketplace_providers import get_oauth_provider
from .models import (
    authorization_service_write,
    marketplace_active_identity_key,
    marketplace_authorization_api_type,
)
from .oauth_diagnostics import oauth_stage, failure_diagnostic
from .oauth_state_service import require_unchanged_configuration

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
    if (platform == "tiktok" and integration_config is not None
            and marketplace_authorization_api_type(integration_config) == "advertising"):
        from .oauth_errors import OAUTH_PROVIDER_UNAVAILABLE
        raise OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "TikTok Ads requires its independent authorization flow.")
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


def start_marketplace_oauth(*, actor, platform, integration_config, store, region, redirect_uri, scopes,
                           tiktok_browser_verifier=None):
    values = dict(actor=actor, platform=platform, integration_config=integration_config,
        store=store, region=region, redirect_uri=redirect_uri, scopes=scopes,
        tiktok_browser_verifier=tiktok_browser_verifier)
    if platform == "tiktok":
        # An unusable start must not leave a pending state or partial browser proof.
        try:
            with transaction.atomic():
                return _start_marketplace_oauth(**values)
        except OAuthFlowError as exc:
            if (actor.tenant_id is not None and actor.tenant_id
                    == getattr(integration_config, "tenant_id", None) == getattr(store, "tenant_id", None)):
                diagnostic = getattr(exc, "diagnostic", None)
                IntegrationAuditLog.objects.create(
                    tenant=actor.tenant, integration_config=integration_config, actor=actor,
                    action="oauth_start", result=IntegrationAuditLog.Result.BLOCKED,
                    masked_detail={"result_code": exc.controlled_code, "platform": platform,
                        "store_id": str(store.pk),
                        **({"diagnostic": {key: value for key, value in diagnostic.items()
                            if key != "oauth_session_id"}} if isinstance(diagnostic, dict) else {})},
                )
            raise
    return _start_marketplace_oauth(**values)


def _start_marketplace_oauth(*, actor, platform, integration_config, store, region, redirect_uri, scopes,
                            tiktok_browser_verifier=None):
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
    try:
        with oauth_stage("validate_callback"):
            url_payload = provider.build_authorization_url(provider_context)
    except OAuthFlowError as exc:
        diagnostic = failure_diagnostic(exc, session)
        _callback_audit(session, actor, IntegrationAuditLog.Result.BLOCKED, exc.controlled_code, diagnostic=diagnostic)
        raise
    result = {
        "platform": platform,
        "authorization_url": url_payload["url"],
        "expires_at": session.expires_at,
    }
    from .capability import live_network_mode_enabled

    if not live_network_mode_enabled():
        result["state"] = state_plaintext
        result["simulation_callback"] = provider.build_simulation_callback(provider_context)
    elif platform == "tiktok" and marketplace_authorization_api_type(integration_config) == "marketplace":
        from .tiktok_direct_callback import prepare_direct_callback
        direct = prepare_direct_callback(session=session, state=state_plaintext, verifier=tiktok_browser_verifier)
        if not direct:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("TK 商城仅支持 SaaS 直连，请先核对专用回调地址；不会使用旧中转服务器。")
        result["direct_callback"] = direct
    return result


def _callback_audit(session, actor, result, result_code, authorization=None, diagnostic=None):
    IntegrationAuditLog.objects.create(
        tenant=session.tenant,
        integration_config=session.integration_config,
        store_authorization=authorization,
        action="oauth_callback",
        actor=actor,
        result=result,
        masked_detail={
            **({"diagnostic": diagnostic} if diagnostic else {}),
            "result_code": result_code,
            "platform": session.platform,
            "store_id": str(session.store_id),
        },
    )


def _require_callback_target_scope(session, *, store_id, integration_config):
    """Recheck the initiating actor at completion, including automatic callbacks."""
    actor = session.initiated_by
    if (
        actor.tenant_id != session.tenant_id
        or integration_config.tenant_id != session.tenant_id
        or actor.user_type != CustomUser.UserType.INTERNAL
        or not user_has_integration_permission(actor, "integrations.store.authorize")
    ):
        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "Callback target is outside the authorized scope.")
    try:
        allowed = integration_values_allowed(
            actor, "integrations.store.authorize", platform=session.platform,
            environment=integration_config.environment, regions=[session.region],
            config_id=integration_config.pk, store_id=store_id,
        )
    except APIException:
        # Scope removal or malformed scope must fail closed with a controlled
        # OAuth error so newly exchanged references are revoked by the caller.
        allowed = False
    if not allowed:
        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "Callback target is outside the authorized scope.")


def _apply_exchange_result(session, exchange_result):
    _require_callback_target_scope(
        session, store_id=session.store_id, integration_config=session.integration_config,
    )
    store_record = exchange_result["platform_store_records"][0]
    platform_store_id = store_record["platform_store_id"]
    api_type = marketplace_authorization_api_type(session.integration_config)
    identity_key = marketplace_active_identity_key(session.platform, session.region, platform_store_id, api_type)
    actor = session.initiated_by
    existing = MarketplaceStoreAuthorization.objects.filter(
        active_platform_identity_key=identity_key,
    ).first()
    if existing is not None:
        if (
            existing.tenant_id != session.tenant_id
            or existing.store_id != session.store_id
            or existing.integration_config_id != session.integration_config_id
        ):
            raise_oauth_error(OAUTH_STORE_BOUND_CONFLICT)
        _require_callback_target_scope(
            session, store_id=existing.store_id, integration_config=existing.integration_config,
        )
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
            defer_previous_revocation=True,
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
        expires_at=exchange_result["expires_at"],
        actor=actor,
    )
    return transition_store_authorization(record, target_status=MarketplaceStoreAuthorization.Status.ACTIVE, actor=actor)


def _revoke_uncommitted_exchange(exchange_result):
    revoker = exchange_result.get("new_reference_revoker") if isinstance(exchange_result, dict) else None
    if revoker is None:
        return True
    try:
        revoker(exchange_result.get("credential_id"), exchange_result.get("token_id"))
    except Exception:
        return False
    return True


def _discard_callback_exchange(exchange_result, session, *, tiktok_manual_recovery):
    cleaned = _revoke_uncommitted_exchange(exchange_result)
    if tiktok_manual_recovery and not cleaned:
        _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED,
                        "TIKTOK_MANUAL_REFERENCE_CLEANUP_PENDING")


def complete_marketplace_oauth_callback(*, platform, query_params, tiktok_manual_recovery=False, tiktok_expected_store_id=None):
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
    context = {"state": state_plaintext, "region": session.region, "scopes": session.requested_scopes}
    tiktok_target = None
    if session.platform == "shopee" and session.store_id:
        context["target_shop_id"] = session.store.external_store_id
        if not context["target_shop_id"]:
            known_shop_ids = set(MarketplaceStoreAuthorization.objects.filter(
                tenant_id=session.tenant_id, store_id=session.store_id,
                platform=session.platform, region=session.region,
                status=MarketplaceStoreAuthorization.Status.ACTIVE,
            ).values_list("platform_store_id", flat=True))
            if len(known_shop_ids) == 1:
                context["target_shop_id"] = known_shop_ids.pop()
    try:
        with oauth_stage("validate_callback"):
            require_unchanged_configuration(session)
            _require_callback_target_scope(session, store_id=session.store_id, integration_config=session.integration_config)
            if tiktok_manual_recovery:
                from apps.masterdata.models import StoreMaster
                if session.platform != "tiktok" or marketplace_authorization_api_type(session.integration_config) != "marketplace":
                    raise_oauth_error(OAUTH_CALLBACK_REJECTED)
                store = StoreMaster.objects.select_related("platform").get(pk=session.store_id, tenant_id=session.tenant_id)
                if not store.external_store_id or store.platform.platform_type != "tiktok" or store.country_code.upper() != session.region.upper():
                    raise_oauth_error(OAUTH_CALLBACK_REJECTED)
                if tiktok_expected_store_id is not None and store.external_store_id != tiktok_expected_store_id:
                    raise_oauth_error(OAUTH_CALLBACK_REJECTED, "TikTok selected shop changed after authorization start.")
                tiktok_target = (store.tenant_id, store.platform_id, store.external_store_id, store.country_code)
                context["target_shop_id"] = store.external_store_id
            provider = resolve_oauth_provider(session.platform, session.integration_config)
            payload = provider.validate_callback(query_params, context)
        payload["scopes"] = session.requested_scopes
        with oauth_stage("exchange_token"):
            exchange_result = provider.exchange_authorization_code(payload)
        try:
            with oauth_stage("save_authorization"), transaction.atomic():
                # Hold the selected config row until the authorization and its audit commit.
                type(session.integration_config).objects.select_for_update().get(pk=session.integration_config_id)
                require_unchanged_configuration(session)
                if tiktok_target is not None:
                    from apps.masterdata.models import StoreMaster
                    store = StoreMaster.objects.select_for_update().get(pk=session.store_id)
                    records = exchange_result.get("platform_store_records") or []
                    if ((store.tenant_id, store.platform_id, store.external_store_id, store.country_code) != tiktok_target
                            or store.platform.platform_type != "tiktok"
                            or len(records) != 1 or records[0].get("platform_store_id") != tiktok_target[2]
                            or str(records[0].get("region") or "").upper() != session.region.upper()):
                        raise_oauth_error(OAUTH_CALLBACK_REJECTED, "TikTok shop does not match the selected store.")
                authorization = _apply_exchange_result(session, exchange_result)
                _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.SUCCESS, "", authorization=authorization)
        except OAuthFlowError:
            _discard_callback_exchange(exchange_result, session, tiktok_manual_recovery=tiktok_manual_recovery)
            raise
        except Exception:
            _discard_callback_exchange(exchange_result, session, tiktok_manual_recovery=tiktok_manual_recovery)
            raise_oauth_error(OAUTH_DATABASE_FAILURE, "Authorization persistence failed.")
    except OAuthFlowError as exc:
        diagnostic = failure_diagnostic(exc, session)
        try:
            fail_oauth_state(session, exc.controlled_code)
            if tiktok_manual_recovery and getattr(exc, "tiktok_cleanup_pending", False):
                _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED,
                                "TIKTOK_MANUAL_REFERENCE_CLEANUP_PENDING")
            _callback_audit(session, session.initiated_by, IntegrationAuditLog.Result.BLOCKED, exc.controlled_code, diagnostic=diagnostic)
        except Exception:
            # The safe diagnostic is already logged; do not mask a DB outage or replay state.
            pass
        raise
    return authorization


@transaction.atomic
def refresh_marketplace_authorization(record, *, actor, expected_token_id=None):
    record = MarketplaceStoreAuthorization.objects.select_for_update().get(pk=record.pk, tenant_id=actor.tenant_id)
    if expected_token_id is not None:
        from .automatic_refresh import require_automatic_refresh
        require_automatic_refresh(record, expected_token_id)
    provider = resolve_oauth_provider(record.platform, record.integration_config)
    result = provider.refresh_authorization(record)
    refreshed = rotate_store_authorization_references(
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
        defer_previous_revocation=True,
    )
    refreshed.last_error_code = ""
    refreshed.status = MarketplaceStoreAuthorization.Status.ACTIVE
    if result.get("authorized_scopes"):
        refreshed.scopes = result["authorized_scopes"]
    with authorization_service_write():
        refreshed.save(update_fields=["status", "last_error_code", "scopes", "updated_at"])
    return refreshed


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
