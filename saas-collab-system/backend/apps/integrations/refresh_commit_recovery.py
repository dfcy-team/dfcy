"""Resume automatic refresh reference commits without replaying token exchange."""
import hashlib
import json
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .custody import CustodyError, get_custody_backend
from .models import AutomaticRefreshAttempt, MarketplaceStoreAuthorization, authorization_service_write
from .oauth_errors import OAUTH_DATABASE_FAILURE, OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError
from .production_settings import get_runtime_platform_config
from .store_authorization_service import rotate_store_authorization_references


LEASE_SECONDS = 720  # Longer than the credential task's 600-second hard limit.


class RefreshCommitPending(OAuthFlowError):
    def __init__(self, error, *, custody_saved=True):
        database_error = isinstance(error, DatabaseError)
        super().__init__(OAUTH_DATABASE_FAILURE if database_error else OAUTH_PROVIDER_UNAVAILABLE,
                         "续期结果正在自动恢复提交；不会重复刷新平台令牌。")
        self.stage = "save_authorization" if database_error else "save_token"
        self.category = "database_failure" if database_error else "service_uncertain"
        self.commit_recovery = True
        self.custody_saved = custody_saved
        self.error_class = type(error).__name__
        self.database_error_number = error.args[0] if error.args and type(error.args[0]) is int else None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scope(record):
    config = record.integration_config
    options = config.platform_config or {}
    app = options.get("partner_id") or options.get("app_key") or options.get("app_id") or get_runtime_platform_config(record.platform).get("app_id")
    return _digest([record.tenant_id, record.pk, record.store_id, record.platform, record.platform_store_id,
                    record.region, config.pk, config.config_version, options.get("api_type", "marketplace"), app])


def lease_expired(data):
    lease = parse_datetime(str((data or {}).get("lease_until") or ""))
    return lease is not None and timezone.is_aware(lease) and lease <= timezone.now()


def manual_refresh_blocked(record, attempt):
    data = (attempt.commit_recovery or {}) if attempt else {}
    if data.get("phase") not in {"exchange_in_flight", "commit_pending"}:
        return False
    # A definitive platform rejection cannot have issued a new token. Keep
    # ambiguous exchanges and saved candidates fenced, even after lease expiry.
    rejected = (attempt.status == "failed" and attempt.failure_category == "authorization_rejected"
                and attempt.finished_at is not None and attempt.finished_at <= timezone.now())
    return not (rejected and data.get("schema") == 1 and data.get("phase") == "exchange_in_flight"
                and lease_expired(data) and not data.get("candidate")
                and not data.get("recover_only") and not data.get("resuming_exchange")
                and data.get("scope") == _scope(record)
                and data.get("source_reference") == _digest(record.token_id)
                and data.get("source_version") == record.credential_reference_version)


def _persist(attempt, data, phase):
    data = {**data, "phase": phase}
    AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(
        commit_recovery=data, status="commit_pending" if phase == "commit_pending" else "running",
        next_retry_at=timezone.now() + timedelta(seconds=60) if phase == "commit_pending" else None)
    attempt.commit_recovery = data
    return data


def _candidate(result):
    expiry = result.get("expires_at")
    if isinstance(expiry, str):
        expiry = parse_datetime(expiry)
    version = result.get("reference_version", result.get("version"))
    if (not isinstance(result.get("credential_id"), str) or not result["credential_id"]
            or not isinstance(result.get("token_id"), str) or not result["token_id"]
            or type(version) is not int
            or not expiry or timezone.is_naive(expiry) or expiry <= timezone.now()):
        raise ValidationError("Saved refresh reference is incomplete or expired; manual recovery is required.")
    return {"credential_id": result["credential_id"], "token_id": result["token_id"],
            "reference_version": version, "expires_at": expiry.isoformat(),
            "credential_mask": {"configured": "********"}}


def _lookup(data):
    found = get_custody_backend().lookup_reference_by_operation(data["operation_id"], include_reference=True)
    if found.get("found") is not True or found.get("status") != "active":
        raise ValidationError("Refresh outcome cannot be recovered from an active custody receipt; do not repeat refresh.")
    candidate = _candidate(found)
    previous = data.get("candidate")
    if previous and any(previous[key] != candidate[key] for key in ("credential_id", "token_id", "reference_version")):
        raise ValidationError("Custody receipt changed; manual recovery is required.")
    return candidate


def _commit(record, actor, attempt, data, callbacks=None):
    candidate = _candidate(data["candidate"])
    with transaction.atomic():
        current = MarketplaceStoreAuthorization.objects.select_for_update().select_related("integration_config").get(
            pk=record.pk, tenant_id=actor.tenant_id)
        if current.status != "active" or _scope(current) != data["scope"]:
            raise ValidationError("Refresh authorization or application changed; saved references remain isolated.")
        same_candidate = (current.token_id == candidate["token_id"]
                          and current.credential_id == candidate["credential_id"]
                          and current.credential_reference_version == candidate["reference_version"])
        if not same_candidate:
            if (_digest(current.token_id) != data["source_reference"]
                    or current.credential_reference_version != data["source_version"]
                    or candidate["reference_version"] != data["source_version"] + 1):
                raise ValidationError("Refresh generation changed; saved references remain isolated.")
            live = data["reference_kind"] == "custody"
            revoker = get_custody_backend().revoke if live and callbacks is None else None
            callbacks = callbacks or {}
            current = rotate_store_authorization_references(
                current, credential_id=candidate["credential_id"], token_id=candidate["token_id"],
                version=candidate["reference_version"], actor=actor,
                expires_at=parse_datetime(candidate["expires_at"]), credential_mask=candidate["credential_mask"],
                allow_live_references=live,
                revoker=callbacks.get("previous_reference_revoker") or revoker,
                new_reference_revoker=callbacks.get("new_reference_revoker") or revoker,
                defer_previous_revocation=True, preserve_new_reference_on_failure=True)
            current.status, current.last_error_code = "active", ""
            if data.get("authorized_scopes"):
                current.scopes = data["authorized_scopes"]
            with authorization_service_write():
                current.save(update_fields=["status", "last_error_code", "scopes", "updated_at"])
        # Commit the receipt and authorization atomically, including ambiguous DB acknowledgments.
        AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(
            commit_recovery={**data, "phase": "committed"}, status="success", next_retry_at=None)
    return current


def refresh_with_commit_recovery(record, *, actor, expected_token_id):
    from .automatic_refresh import _attempt_key, require_automatic_refresh
    from .marketplace_oauth_service import resolve_oauth_provider

    attempt = AutomaticRefreshAttempt.objects.get(pk=_attempt_key(record), tenant_id=actor.tenant_id)
    data = attempt.commit_recovery or {}
    with transaction.atomic():
        record = MarketplaceStoreAuthorization.objects.select_for_update().select_related("integration_config").get(
            pk=record.pk, tenant_id=actor.tenant_id)
        require_automatic_refresh(record, expected_token_id)
        if data:
            if (data.get("schema") != 1 or data.get("scope") != _scope(record)
                    or data.get("operation_id") != "automatic-refresh:" + attempt.pk):
                raise ValidationError("Refresh application binding changed; manual recovery is required.")
        else:
            data = {"schema": 1, "scope": _scope(record), "source_reference": _digest(record.token_id),
                    "source_version": record.credential_reference_version,
                    "operation_id": "automatic-refresh:" + attempt.pk,
                    "lease_until": (timezone.now() + timedelta(seconds=LEASE_SECONDS)).isoformat()}
            data = _persist(attempt, data, "exchange_in_flight")
    callbacks = None
    try:
        if data.get("candidate") or data.get("recover_only"):
            candidate = _lookup(data)
            data.setdefault("reference_kind", "custody")
        else:
            # An expired in-flight lease has no permission to issue another exchange.
            if data.get("resuming_exchange"):
                candidate = _lookup(data)
                data.setdefault("reference_kind", "custody")
            else:
                record._refresh_operation_id = data["operation_id"]
                try:
                    result = resolve_oauth_provider(record.platform, record.integration_config).refresh_authorization(record)
                except Exception as error:
                    from .automatic_refresh import _refresh_failure_detail
                    if _refresh_failure_detail(error)["safe_to_retry"]:
                        AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(commit_recovery={})
                        raise
                    # Response loss may still leave a custody receipt; never repeat the platform call.
                    try:
                        candidate = _lookup(data)
                    except Exception:
                        raise error from None
                    data["reference_kind"] = "custody"
                else:
                    candidate = _candidate(result)
                    callbacks = result
                    data.update(reference_kind=result.get("reference_kind", "synthetic"),
                                authorized_scopes=result.get("authorized_scopes") or [])
        data["candidate"] = candidate
        data = _persist(attempt, data, "commit_pending")
        return _commit(record, actor, attempt, data, callbacks)
    except DatabaseError as error:
        if not data.get("candidate"):
            raise
        # A lost COMMIT acknowledgment is not proof of rollback.
        try:
            saved = MarketplaceStoreAuthorization.objects.select_related("integration_config").filter(
                pk=record.pk, tenant_id=actor.tenant_id, status="active",
                token_id=data["candidate"]["token_id"], credential_id=data["candidate"]["credential_id"],
                credential_reference_version=data["candidate"]["reference_version"]).first()
            if saved and _scope(saved) == data["scope"]:
                AutomaticRefreshAttempt.objects.filter(pk=attempt.pk).update(
                    commit_recovery={**data, "phase": "committed"}, status="success", next_retry_at=None)
                return saved
        except DatabaseError:
            pass
        # The journal/receipt is durable; make only the DB commit eligible for bounded retry.
        data.update(lease_until=timezone.now().isoformat(), recover_only=True)
        try:
            _persist(attempt, data, "commit_pending")
        except DatabaseError:
            pass  # Expired in-flight ownership will reconcile custody after DB recovery.
        raise RefreshCommitPending(error) from None
    except CustodyError as error:
        if not (data.get("candidate") or data.get("recover_only") or data.get("resuming_exchange")):
            raise
        data.update(lease_until=timezone.now().isoformat(), recover_only=True)
        try:
            _persist(attempt, data, "commit_pending")
        except DatabaseError:
            pass
        raise RefreshCommitPending(error, custody_saved=bool(data.get("candidate"))) from None
    except Exception as error:
        if data.get("candidate"):
            error.custody_saved = True
            error.error_class = type(error).__name__
        raise
