"""Two-phase TikTok shop discovery. No codes, plaintext tokens or ciphers leave here."""
from contextlib import contextmanager
from datetime import timedelta
import uuid
import re

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.masterdata.models import StoreMaster
from . import marketplace_oauth_service as oauth
from .credential_service import RAW_CREDENTIAL_FIELDS, build_reference_metadata
from .custody import get_custody_backend
from .models import (MarketplaceStoreAuthorization, OAuthStateSession, PlatformIntegrationConfig,
                     TikTokShopBindingSession as Binding, shop_binding_service_write,
                     marketplace_authorization_api_type, marketplace_active_identity_key)
from .oauth_errors import OAuthFlowError, OAUTH_CALLBACK_REJECTED, OAUTH_STORE_BOUND_CONFLICT
from .oauth_state_service import consume_oauth_state, oauth_state_digest, require_unchanged_configuration
from .oauth_diagnostics import oauth_stage, failure_diagnostic


def _reject(conflict=False):
    raise OAuthFlowError(OAUTH_STORE_BOUND_CONFLICT if conflict else OAUTH_CALLBACK_REJECTED,
                         "Shop binding is unavailable or has changed; restart authorization.")


def _identity(store):
    return {"tenant_id": store.tenant_id, "platform_id": store.platform_id,
            "region": store.country_code.upper(), "external_store_id": store.external_store_id}


def _previous_reference_revoker(revoker, *, synchronous_owner_id=None):
    def revoke(credential_id, token_id):
        owners = MarketplaceStoreAuthorization.objects.filter(
            Q(credential_id=credential_id) | Q(token_id=token_id))
        # Synthetic rotation calls synchronously before replacing its own refs;
        # live on_commit cleanup must check ALL owners, including the rotated row.
        if synchronous_owner_id is not None:
            owners = owners.exclude(pk=synchronous_owner_id)
        if owners.exists():
            return {"status": "failed", "error_code": "REFERENCES_OWNED"}
        return revoker(credential_id, token_id)
    return revoke


def _validate(actor, session, store, *, expected_identity=None):
    try:
        actor = CustomUser.objects.select_related("tenant").get(pk=actor.pk)
        session.initiated_by = CustomUser.objects.get(pk=session.initiated_by_id)
        config = session.integration_config
        require_unchanged_configuration(session)
    except ObjectDoesNotExist:
        _reject()
    if (not actor.is_active or actor.pk != session.initiated_by_id
            or actor.tenant_id != session.tenant_id or actor.user_type != "internal"
            or actor.tenant.status != "active"
            or config.tenant_id != session.tenant_id or store.tenant_id != session.tenant_id
            or session.platform != "tiktok" or config.platform != "tiktok"
            or marketplace_authorization_api_type(config) != "marketplace"
            or config.status not in {"configured", "verified", "active"}
            or config.deleted_at is not None or store.status != "active"
            or store.platform.platform_type != "tiktok"
            or store.platform.tenant_id != session.tenant_id or store.platform.status != "active"
            or store.country_code.upper() != session.region.upper()
            or session.region.upper() not in {str(r).upper() for r in config.regions}
            or (expected_identity is not None and _identity(store) != expected_identity)):
        _reject()
    oauth._require_callback_target_scope(session, store_id=store.pk, integration_config=config)
    return actor


@contextmanager
def _locked(binding_id):
    # Every mutator takes config -> store -> binding, including cleanup.
    hint = Binding.objects.get(pk=binding_id)
    with transaction.atomic(), shop_binding_service_write():
        config = PlatformIntegrationConfig.all_objects.select_for_update().get(pk=hint.integration_config_id)
        store = StoreMaster.objects.select_for_update().select_related("platform").get(pk=hint.store_id)
        row = Binding.objects.select_for_update().select_related("oauth_session", "authorization").get(pk=binding_id)
        row.integration_config = config
        row.store = store
        row.oauth_session.integration_config = config
        row.oauth_session.store = store
        yield row


def _owned(actor, binding_id):
    from django.core.exceptions import ValidationError
    try:
        row = Binding.objects.filter(pk=binding_id, tenant_id=actor.tenant_id, initiated_by_id=actor.pk).first()
    except (ValidationError, ValueError, TypeError):
        _reject()
    if row is None:
        _reject()
    return row


def _public(row):
    base = {"status": row.status, "binding_id": str(row.pk), "store_id": row.store_id,
            "store_code": row.store.code, "store_name": row.store.name, "region": row.region,
            "expires_at": row.expires_at}
    if row.status == Binding.Status.BOUND:
        base.update(authorization_id=row.authorization_id, platform_store_id=row.selected_platform_store_id)
        authorization = row.authorization
        base["authorization"] = {"id": authorization.pk, "status": authorization.status,
            "store_id": authorization.store_id, "platform": authorization.platform,
            "platform_store_id": authorization.platform_store_id, "region": authorization.region}
    elif row.status == Binding.Status.PENDING:
        base["candidates"] = [{"platform_store_id": r["platform_store_id"],
                               "name": r.get("name", ""), "region": r["region"]}
                              for r in row.exchange_data.get("platform_store_records", [])]
    return base


def _stage(result, region):
    # Explicit allow-list: never persist callable revokers, raw secrets or arbitrary provider metadata.
    records = result.get("platform_store_records") or []
    if not records or len(records) > 1000:
        _reject()
    candidates, seen = [], set()
    for record in records:
        sid = str(record.get("platform_store_id") or "").strip()
        country = str(record.get("region") or "").upper()
        cipher = str(record.get("shop_cipher") or "")
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", sid) or sid in seen or country != region
                or not cipher or len(cipher) > 255 or any(c.isspace() for c in cipher)):
            _reject()
        seen.add(sid)
        candidates.append({"platform_store_id": sid, "region": country,
                           "name": str(record.get("name") or record.get("shop_name") or "")[:160],
                           "shop_cipher": cipher})
    subject = result.get("platform_subject")
    scopes = result.get("authorized_scopes")
    if (not isinstance(subject, str) or not subject or len(subject) > 160
            or not isinstance(scopes, list) or len(scopes) > 200
            or any(not isinstance(scope, str) or not scope or len(scope) > 160 for scope in scopes)
            or any(not isinstance(result.get(key), str) or not result[key] or len(result[key]) > 160
                   for key in ("credential_id", "token_id"))):
        _reject()
    mask = result.get("credential_mask")
    mask = ({key: "********" for key in ("credential", "token", "configured") if mask.get(key)}
            if isinstance(mask, dict) else None)
    metadata = build_reference_metadata(result["credential_id"], result["token_id"], 1,
        credential_mask=mask, allow_live=result.get("reference_kind") == "custody")
    return {"credential_id": str(result["credential_id"]), "token_id": str(result["token_id"]),
            "credential_mask": metadata["credential_mask"],
            "reference_kind": result.get("reference_kind", ""),
            "platform_subject": subject,
            "authorized_scopes": scopes,
            "expires_at": result["expires_at"].isoformat(), "platform_store_records": candidates}


def start_shop_binding(actor, query_params, callback_state_verified=False, expected_store_id=None,
                       manual_import_confirmed=False):
    """Trusted direct-callback caller only; expected_store_id is verified browser proof,
    never a client-submitted target. Missing provider state requires either a
    known target or explicit manual import on a validated direct/browser session.
    """
    known = expected_store_id is not None
    if (type(callback_state_verified) is not bool or type(manual_import_confirmed) is not bool
            or transaction.get_connection().in_atomic_block
            or (manual_import_confirmed and (known or callback_state_verified))
            or (known and (not isinstance(expected_store_id, str)
                          or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", expected_store_id)))
            or (not known and callback_state_verified is not True and not manual_import_confirmed)):
        # An enclosing request transaction cannot promise durable operation evidence before HTTP.
        _reject()
    if (RAW_CREDENTIAL_FIELDS | oauth.CALLBACK_FORBIDDEN_CONTEXT_FIELDS).intersection(
            str(k).lower() for k in query_params):
        _reject()
    state = str(query_params.get("state") or "")
    session = OAuthStateSession.objects.filter(state_hash=oauth_state_digest(state)).first()
    if session is None or session.store_id is None:
        _reject()
    with transaction.atomic(), shop_binding_service_write():
        config = PlatformIntegrationConfig.all_objects.select_for_update().get(pk=session.integration_config_id)
        store = StoreMaster.objects.select_for_update().select_related("platform").get(pk=session.store_id)
        session.integration_config = config
        session.store = store
        _validate(actor, session, store)
        # Explicit credential import is not provider-returned OAuth state proof.
        # The direct endpoint has verified the signed actor/browser context first.
        if manual_import_confirmed and (session.callback_transport != "direct"
                or not re.fullmatch(r"[a-f0-9]{64}", session.browser_verifier_hash or "")):
            _reject()
        if known and (store.external_store_id != expected_store_id
                      or (not callback_state_verified and (
                          session.callback_transport != "direct"
                          or not re.fullmatch(r"[a-f0-9]{64}", session.browser_verifier_hash)))):
            _reject(True)
        if not known and store.external_store_id:
            _reject(True)
        session = consume_oauth_state(state, platform="tiktok")
        binding_id = uuid.uuid4()
        row = Binding.objects.create(id=binding_id, operation_id=binding_id,
            oauth_session=session, tenant_id=session.tenant_id,
            initiated_by_id=session.initiated_by_id, integration_config=config, store=store,
            region=session.region.upper(), configuration_digest=session.configuration_digest,
            store_identity=_identity(store), expires_at=timezone.now() + timedelta(minutes=15))
        if manual_import_confirmed:
            oauth._callback_audit(session, actor, "success", "MANUAL_IMPORT_REQUESTED")
    try:
        provider = oauth.resolve_oauth_provider("tiktok", config)
        context = {"state": state, "region": row.region, "scopes": session.requested_scopes}
        if known:
            context["target_shop_id"] = expected_store_id
        with oauth_stage("validate_callback"):
            payload = provider.validate_callback(query_params, context)
        payload.update(custody_operation_id=str(row.operation_id), scopes=session.requested_scopes)
        if known:
            payload.pop("discover_shop_binding", None)
            payload["target_shop_id"] = expected_store_id
        else:
            payload["discover_shop_binding"] = True
        with oauth_stage("exchange_token"):
            result = provider.exchange_authorization_code(payload)
        # Save references even when candidate validation fails, so cleanup can retry durably.
        with _locked(row.pk) as current:
            if current.status != Binding.Status.EXCHANGING:
                _reject()
            current.exchange_data = {key: str(result.get(key) or "") for key in ("credential_id", "token_id")}
            current.save()
        with oauth_stage("verify_store"):
            data = _stage(result, row.region)
        if known and (len(data["platform_store_records"]) != 1
                      or data["platform_store_records"][0]["platform_store_id"] != expected_store_id):
            _reject(True)
        with _locked(row.pk) as current:
            if current.status != Binding.Status.EXCHANGING:
                _reject()
            _validate(actor, current.oauth_session, current.store, expected_identity=current.store_identity)
            current.exchange_data = data
            current.expires_at = min(current.expires_at, result["expires_at"])
            if current.expires_at <= timezone.now():
                _reject()
            current.status = Binding.Status.PENDING
            current.save()
            return _public(current)
    except Exception as original:
        with _locked(row.pk) as current:
            if current.status == Binding.Status.EXCHANGING:
                current.status = Binding.Status.CLEANUP
                current.cleanup_error = "EXCHANGE_INCOMPLETE"
                current.save()
        # Retain only closed-schema evidence, never exception text or OAuth payloads.
        exc = original if isinstance(original, OAuthFlowError) else OAuthFlowError(OAUTH_CALLBACK_REJECTED)
        diagnostic = failure_diagnostic(exc, session)
        oauth._callback_audit(session, actor, "failed", exc.controlled_code, diagnostic=diagnostic)
        raise exc from None


def complete_bound_shop_authorization(actor, query_params, expected_store_id, callback_state_verified):
    """Stage exact-target reauthorization, then auto-confirm without a shop picker.

    Caller must first validate the direct signed browser token and verifier;
    callback_state_verified describes the original provider state, never an injected one.
    Returns the same safe discriminated bound dict as confirm_shop_binding.
    """
    if not expected_store_id:
        _reject()
    pending = start_shop_binding(actor, query_params, callback_state_verified=callback_state_verified,
                                 expected_store_id=expected_store_id)
    try:
        return confirm_shop_binding(actor, pending["binding_id"], expected_store_id)
    except Exception:
        # Confirmation rolled back, but its operation/ref evidence was committed before exchange.
        # Never revoke here: a concurrent/retried confirmation may already own the references.
        try:
            with _locked(pending["binding_id"]) as row:
                if row.status in {Binding.Status.PENDING, Binding.Status.EXCHANGING}:
                    row.status = Binding.Status.CLEANUP
                    row.cleanup_error = "AUTHORIZATION_PERSISTENCE_INCOMPLETE"
                    row.save()
        except Exception:
            # Even a DB outage leaves a durable pending/exchanging row for expiry cleanup.
            pass
        raise OAuthFlowError(OAUTH_CALLBACK_REJECTED,
            "Shop authorization failed; reconciliation is pending.") from None


def get_binding(actor, binding_id):
    row = _owned(actor, binding_id)
    _validate(actor, row.oauth_session, row.store)
    if row.status == Binding.Status.PENDING and _identity(row.store) != row.store_identity:
        _reject()
    if row.status == Binding.Status.PENDING and row.expires_at <= timezone.now():
        _reject()
    return _public(row)


def confirm_shop_binding(actor, binding_id, platform_store_id):
    _owned(actor, binding_id)
    with _locked(binding_id) as row:
        _validate(actor, row.oauth_session, row.store)
        if row.configuration_digest != row.oauth_session.configuration_digest:
            _reject()
        if row.status == Binding.Status.BOUND:
            if (row.selected_platform_store_id != platform_store_id
                    or row.store.external_store_id != platform_store_id or not row.authorization_id):
                _reject(True)
            return _public(row)
        if row.status != Binding.Status.PENDING or row.expires_at <= timezone.now():
            _reject()
        known = bool(row.store_identity.get("external_store_id"))
        if (_identity(row.store) != row.store_identity
                or (known and row.store.external_store_id != platform_store_id)):
            _reject(True)
        records = [r for r in row.exchange_data["platform_store_records"]
                   if r["platform_store_id"] == platform_store_id and r["region"] == row.region]
        if len(records) != 1:
            _reject()
        from django.utils.dateparse import parse_datetime
        data = {**row.exchange_data, "expires_at": parse_datetime(row.exchange_data["expires_at"])}
        if not data["expires_at"] or data["expires_at"] <= timezone.now():
            _reject()
        if MarketplaceStoreAuthorization.objects.filter(
                Q(credential_id=data["credential_id"]) | Q(token_id=data["token_id"])).exists():
            _reject(True)
        if known:
            if len(data["platform_store_records"]) != 1:
                _reject(True)
            identity_key = marketplace_active_identity_key("tiktok", row.region, platform_store_id,
                marketplace_authorization_api_type(row.integration_config))
            previous = MarketplaceStoreAuthorization.objects.select_for_update().filter(
                active_platform_identity_key=identity_key).first()
            if previous is not None:
                if (previous.tenant_id != row.tenant_id or previous.store_id != row.store_id
                        or previous.integration_config_id != row.integration_config_id):
                    _reject(True)
                if (previous.credential_id, previous.token_id) != (data["credential_id"], data["token_id"]):
                    # Commit this outbox in the SAME transaction as rotation and bound status.
                    # The existing on_commit revoker is best-effort; this survives its failure/crash.
                    row.exchange_data = {**row.exchange_data,
                        "previous_reference": {"credential_id": previous.credential_id,
                            "token_id": previous.token_id, "authorization_id": previous.pk,
                            "reference_version": previous.credential_reference_version},
                        "previous_reference_cleanup": "pending",
                        "previous_reference_cleanup_attempts": 0,
                        "previous_reference_cleanup_error": ""}
                    row.save()
            provider = oauth.resolve_oauth_provider("tiktok", row.integration_config)
            previous_revoker = _previous_reference_revoker(provider.custody.revoke,
                synchronous_owner_id=(previous.pk if previous is not None
                                      and data.get("reference_kind") != "custody" else None))
            data.update(previous_reference_revoker=previous_revoker,
                        new_reference_revoker=provider.custody.revoke)
            row.authorization = oauth._apply_exchange_result(row.oauth_session, data)
        else:
            row.store.external_store_id = platform_store_id
            row.store.save(update_fields=["external_store_id", "updated_at"])
            row.authorization = oauth._create_authorization_from_exchange(row.oauth_session, data, records[0])
        oauth._callback_audit(row.oauth_session, actor, "success", "TIKTOK_SHOP_BOUND", authorization=row.authorization)
        row.selected_platform_store_id = platform_store_id
        row.status = Binding.Status.BOUND
        row.save()
        return _public(row)


def cancel_shop_binding(actor, binding_id):
    _owned(actor, binding_id)
    with _locked(binding_id) as row:
        _validate(actor, row.oauth_session, row.store)
        if row.status == Binding.Status.BOUND:
            _reject(True)
        if row.status not in {Binding.Status.CLEANED, Binding.Status.CLEANING}:
            row.status = Binding.Status.CANCELLED
            row.save()
        return _public(row)


def cleanup_shop_bindings(limit=50):
    limit = max(0, min(int(limit), 100))
    now = timezone.now()
    eligible = (Q(status__in=[Binding.Status.CANCELLED, Binding.Status.CLEANUP])
                | Q(status=Binding.Status.PENDING, expires_at__lte=now)
                | Q(status=Binding.Status.EXCHANGING, updated_at__lte=now - timedelta(minutes=2))
                | Q(status=Binding.Status.CLEANING, cleanup_lease_until__lte=now))
    ids = list(Binding.objects.filter(eligible).order_by("updated_at").values_list("pk", flat=True)[:limit])
    summary = {"claimed": 0, "cleaned": 0, "retry": 0, "owned": 0}
    for binding_id in ids:
        with _locked(binding_id) as row:
            if not Binding.objects.filter(pk=binding_id).filter(eligible).exists():
                continue
            fence = uuid.uuid4()
            row.status = Binding.Status.CLEANING
            row.cleanup_fence = fence
            row.cleanup_lease_until = timezone.now() + timedelta(minutes=5)
            row.cleanup_attempts += 1
            row.save()
            data, operation_id = dict(row.exchange_data), row.operation_id
        summary["claimed"] += 1
        outcome, error = "retry", "CUSTODY_RECONCILIATION_PENDING"
        try:
            # Cleanup must remain available after platform live mode/config is disabled.
            # The custody factory retains its own backend/authentication/security boundary.
            custody = get_custody_backend()
            # Atomic permanent tombstone fences a late custody store, even when absent.
            lookup = custody.lookup_reference_by_operation(str(operation_id), close=True)
            if not isinstance(lookup, dict) or type(lookup.get("found")) is not bool:
                raise RuntimeError("Unconfirmed operation closure")
            if lookup["found"]:
                recovered = {k: str(lookup.get(k) or "") for k in ("credential_id", "token_id")}
                if not all(recovered.values()):
                    raise RuntimeError("Incomplete references")
                if any(data.get(k) and data[k] != recovered[k] for k in recovered):
                    raise RuntimeError("Operation reference mismatch")
                data.update(recovered)
            if not lookup["found"] and (not data.get("credential_id") or not data.get("token_id")):
                outcome, error = "cleaned", ""
            else:
                with _locked(binding_id) as row:
                    if row.status != Binding.Status.CLEANING or row.cleanup_fence != fence:
                        continue
                    row.exchange_data = {**row.exchange_data, **data}
                    row.save()
                    owned = MarketplaceStoreAuthorization.objects.filter(
                        Q(credential_id=data["credential_id"]) | Q(token_id=data["token_id"])).exists()
                if owned:
                    outcome, error = "owned", "REFERENCES_OWNED"
                else:
                    revoked = custody.revoke(data["credential_id"], data["token_id"])
                    if not isinstance(revoked, dict) or revoked.get("status") != "revoked":
                        raise RuntimeError("Revocation unconfirmed")
                    outcome, error = "cleaned", ""
        except Exception:
            pass
        with _locked(binding_id) as row:
            if row.status != Binding.Status.CLEANING or row.cleanup_fence != fence:
                continue
            row.status = Binding.Status.CLEANED if outcome in {"cleaned", "owned"} else Binding.Status.CLEANUP
            row.cleanup_error = error
            row.cleanup_lease_until = None
            row.save()
        summary[outcome] += 1
    return summary


def cleanup_previous_shop_references(limit=50):
    """Drain committed reauthorization outboxes; never close/revoke the new operation.

    Shares the row lease/fence with abandoned-exchange cleanup, whose eligible
    statuses exclude bound rows. All external revocation runs outside DB locks.
    """
    limit = max(0, min(int(limit), 100))
    now = timezone.now()
    eligible = (Q(status=Binding.Status.BOUND, exchange_data__previous_reference_cleanup="pending")
                & (Q(cleanup_lease_until__isnull=True) | Q(cleanup_lease_until__lte=now)))
    ids = list(Binding.objects.filter(eligible).order_by("updated_at").values_list("pk", flat=True)[:limit])
    summary = {"claimed": 0, "cleaned": 0, "retry": 0, "owned": 0}
    for binding_id in ids:
        with _locked(binding_id) as row:
            if not Binding.objects.filter(pk=binding_id).filter(eligible).exists():
                continue
            fence = uuid.uuid4()
            row.cleanup_fence = fence
            row.cleanup_lease_until = timezone.now() + timedelta(minutes=5)
            row.exchange_data = {**row.exchange_data,
                "previous_reference_cleanup_attempts": row.exchange_data.get("previous_reference_cleanup_attempts", 0) + 1}
            row.save()
            previous = dict(row.exchange_data.get("previous_reference") or {})
        summary["claimed"] += 1
        outcome, error = "retry", "PREVIOUS_REFERENCE_CLEANUP_PENDING"
        try:
            credential_id, token_id = previous.get("credential_id"), previous.get("token_id")
            if any(not isinstance(value, str) or not value or len(value) > 160
                   for value in (credential_id, token_id)):
                raise ValueError("Incomplete previous references")
            with _locked(binding_id) as row:
                if (row.status != Binding.Status.BOUND or row.cleanup_fence != fence
                        or row.exchange_data.get("previous_reference_cleanup") != "pending"
                        or row.exchange_data.get("previous_reference") != previous):
                    continue
                # A pair overlapping the staged new reference must never be revoked,
                # even if that newer authorization has subsequently rotated again.
                overlap = (credential_id == row.exchange_data.get("credential_id")
                           or token_id == row.exchange_data.get("token_id"))
                owned = MarketplaceStoreAuthorization.objects.filter(
                    Q(credential_id=credential_id) | Q(token_id=token_id)).exists()
            if overlap or owned:
                outcome, error = "owned", "PREVIOUS_REFERENCES_OWNED"
            else:
                custody = get_custody_backend()
                revoked = custody.revoke(credential_id, token_id)
                if not isinstance(revoked, dict) or revoked.get("status") != "revoked":
                    raise RuntimeError("Previous reference revocation unconfirmed")
                outcome, error = "cleaned", ""
        except Exception:
            pass
        with _locked(binding_id) as row:
            if (row.status != Binding.Status.BOUND or row.cleanup_fence != fence
                    or row.exchange_data.get("previous_reference_cleanup") != "pending"
                    or row.exchange_data.get("previous_reference") != previous):
                continue
            row.exchange_data = {**row.exchange_data,
                "previous_reference_cleanup": "pending" if outcome == "retry" else outcome,
                "previous_reference_cleanup_error": error}
            row.cleanup_lease_until = None
            row.save()
        summary[outcome] += 1
    return summary
