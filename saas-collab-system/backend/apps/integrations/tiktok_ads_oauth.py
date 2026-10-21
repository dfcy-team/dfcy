"""Independent Ads authorization. No report, sync, or publication operations."""
import hashlib
import json
import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.masterdata.models import StoreMaster
from apps.permissions.services import user_has_integration_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .capability import require_live_mode
from .custody import HttpCustodyBackend, get_custody_backend
from .models import AdsOAuthSession, IntegrationAuditLog, PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, marketplace_authorization_api_type
from .net_guard import PlatformHttpClient
from .oauth_state_service import configuration_digest
from .production_settings import get_runtime_platform_config, get_runtime_setting

HOST = "https://business-api.tiktok.com/open_api/v1.3/"
MAX_CANDIDATES = 500


class Conflict(APIException):
    status_code = 409
    default_detail = "广告授权状态冲突，请刷新核对；不会改绑其他店铺的账户。"


class LegacyCallbackGone(APIException):
    status_code = 410
    default_detail = "Legacy Ads callbacks are disabled. Start a new direct authorization."


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(config):
    return configuration_digest(config)


def scope(actor, store, config, *, read_only=False):
    if (actor.user_type != "internal" or not actor.is_active
            or actor.tenant_id != store.tenant_id or actor.tenant_id != config.tenant_id
            or store.platform.tenant_id != actor.tenant_id
            or store.status != "active" or store.platform.status != "active" or actor.tenant.status != "active"
            or store.platform.platform_type != "tiktok"
            or config.regions and store.country_code.upper() not in {str(region).upper() for region in config.regions}
            or not user_has_integration_permission(actor, "integrations.store.authorize")
            or not integration_values_allowed(actor, "integrations.store.authorize", platform="tiktok",
                environment=config.environment, regions=[store.country_code], store_id=store.pk, config_id=config.pk)):
        raise PermissionDenied("当前角色无权操作此店铺或广告配置。")
    if read_only:
        return
    from .tiktok_ads_direct import configured_callback
    direct_callback = configured_callback()
    require_live_mode("TikTok Ads authorization")
    if (config.platform != "tiktok" or marketplace_authorization_api_type(config) != "advertising"
            or config.deleted_at or config.status not in {"verified", "active"} or config.environment not in {"pilot", "production"}
            or not config.network_enabled or not config.sync_read_enabled or config.sync_write_enabled
            or not get_runtime_platform_config("tiktok").get("contract_approved")
            or not direct_callback or config.callback_url != direct_callback
            or config.callback_url not in (get_runtime_setting("network", "oauth_redirect_allowlist", default=[]) or [])
            or not re.fullmatch(r"[0-9]{5,40}", str(config.platform_config.get("app_id", "")))
            or not config.contract_version or not config.credential_id or config.credential_revoked_at
            or config.credential_status != "configured"
            or config.credential_expires_at and config.credential_expires_at <= timezone.now()):
        raise ValidationError("广告配置尚未就绪，请联系管理员核对审核、只读开关和回调设置。")


def load(actor, session_id, *, lock=False, read_only=False):
    query = AdsOAuthSession.objects.select_for_update() if lock else AdsOAuthSession.objects
    session = query.select_related("store__platform", "integration_config").filter(
        pk=session_id, tenant_id=actor.tenant_id, actor_id=actor.pk).first()
    if session is None:
        raise PermissionDenied("本次广告授权不可访问，请返回原店铺核对。")
    # Refresh actor permissions from persistent state, not callback claims.
    actor.refresh_from_db()
    scope(actor, session.store, session.integration_config, read_only=read_only)
    if read_only:
        return session
    if session.config_fingerprint != fingerprint(session.integration_config):
        raise Conflict("广告配置已变更，请从原店铺重新发起授权。")
    if session.expires_at <= timezone.now():
        raise Conflict("本次广告授权已过期，请从原店铺重新发起。")
    if session.status == "exchanging" and session.consumed_at and session.consumed_at < timezone.now() - timedelta(seconds=120):
        AdsOAuthSession.objects.filter(pk=session.pk, status="exchanging").update(status="unknown")
        session.status = "unknown"
    return session


def audit(session, actor, event, result="success"):
    IntegrationAuditLog.objects.create(tenant_id=session.tenant_id, integration_config_id=session.integration_config_id,
        actor=actor, action="ads_oauth_" + event, result=result,
        masked_detail={"session_id": str(session.pk), "store_id": session.store_id, "event": event})


def sanitized(session):
    fields = ("advertiser_id", "name", "currency", "timezone", "verify_state", "reason", "verified_at")
    return {"session_id": str(session.pk), "store_id": session.store_id, "status": session.status,
        "expires_at": session.expires_at, "candidates": [{k: c.get(k, "") for k in fields} for c in session.candidates],
        "bindings": session.binding_results, "report_data_ingested": False}


def start(actor, store_id, config_id, tiktok_browser_verifier=None):
    from .tiktok_ads_direct import configured_callback, prepare
    actor.refresh_from_db()
    store = StoreMaster.objects.select_related("platform").filter(pk=store_id, tenant_id=actor.tenant_id).first()
    config = PlatformIntegrationConfig.objects.filter(pk=config_id, tenant_id=actor.tenant_id).first()
    if not store or not config:
        raise PermissionDenied("店铺或广告配置不可访问。")
    scope(actor, store, config)
    state = "saas_ads_" + secrets.token_urlsafe(32)
    session = AdsOAuthSession(tenant_id=actor.tenant_id, store=store, integration_config=config, actor=actor,
        state_hash=digest(state), config_fingerprint=fingerprint(config), expires_at=timezone.now() + timedelta(seconds=600))
    if configured_callback() and config.callback_url == configured_callback():
        direct = prepare(session, tiktok_browser_verifier)
        with transaction.atomic():
            session.save()
            audit(session, actor, "start")
        return {"session_id": str(session.pk), "expires_at": session.expires_at,
            "authorization_url": "https://business-api.tiktok.com/portal/auth?" + urlencode({
                "app_id": str(config.platform_config["app_id"]), "state": state, "redirect_uri": config.callback_url}),
            "direct_callback": direct}
    raise ValidationError("Ads direct callback is required; legacy relay is disabled.")


def custody():
    backend = get_custody_backend()
    if not isinstance(backend, HttpCustodyBackend):
        raise ValidationError("独立凭据保管服务尚未就绪，请联系管理员。")
    return backend


def request_json(session, method, url, *, body=None, token=None, platform=True):
    response = PlatformHttpClient().request(method, url, json_body=body,
        headers={"Access-Token": token} if token else {}, retry=False,
        connect_timeout=min(session.integration_config.connect_timeout_seconds, 5),
        read_timeout=min(session.integration_config.read_timeout_seconds, 15), diagnostic_platform="tiktok_ads")
    try:
        payload = response.json()
    except (TypeError, ValueError):
        raise ValidationError("广告平台响应无法确认，请核对授权状态。") from None
    if not isinstance(payload, dict):
        raise ValidationError("广告平台响应无法确认，请核对授权状态。")
    if platform:
        if payload.get("code") not in (0, "0") or not isinstance(payload.get("data"), dict):
            raise ValidationError("广告平台未接受请求，请核对账户权限。")
        return payload["data"]
    return payload


def complete(actor, session_id, receipt_id):
    raise LegacyCallbackGone()


def _complete(actor, session_id, *, direct_validator):
    # Commit the one-use claim before custody or platform traffic.
    with transaction.atomic():
        session = load(actor, session_id, lock=True)
        direct_params = direct_validator(session)
        if session.status != "pending" or session.consumed_at:
            raise Conflict("本次授权回执已处理，请刷新状态，不要重复提交。")
        claimed_at = timezone.now()
        claimed = AdsOAuthSession.objects.filter(pk=session.pk, status="pending", consumed_at__isnull=True).update(
            status="exchanging", consumed_at=claimed_at)
        if claimed != 1:
            raise Conflict("本次授权回执已处理，不会再次兑换。")
        session.status, session.consumed_at = "exchanging", claimed_at
        audit(session, actor, "claimed")
    try:
        callback = {"session_id": str(session.pk), "callback_params": direct_params}
        params = callback.get("callback_params", {})
        if (callback.get("session_id") == str(session.pk) and isinstance(params, dict)
                and params.get("error") == "authorization_denied"
                and isinstance(params.get("state"), str) and digest(params["state"]) == session.state_hash):
            with transaction.atomic():
                session = load(actor, session_id, lock=True)
                session.status = "failed"
                session.save(update_fields=["status"])
                audit(session, actor, "denied", "failed")
            return sanitized(session)
        if (callback.get("session_id") != str(session.pk) or not isinstance(params, dict)
                or not isinstance(params.get("state"), str) or digest(params["state"]) != session.state_hash
                or params.get("error") or not isinstance(params.get("auth_code"), str)
                or not 1 <= len(params["auth_code"]) <= 8192):
            raise ValidationError("广告授权回执无效，请返回原店铺核对。")
        session = load(actor, session_id)
        backend = custody()
        secret = backend.retrieve_secret(session.integration_config.credential_id)
        result = request_json(session, "POST", HOST + "oauth2/access_token/", body={
            "app_id": str(session.integration_config.platform_config["app_id"]), "secret": secret,
            "auth_code": params["auth_code"]})
        token = result.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValidationError("广告授权结果无法确认，请核对状态。")
        refs = backend.store_secrets(credential_type="tiktok_ads", access_token=token,
            metadata={"tenant_id": session.tenant_id, "config_id": session.integration_config_id,
                "session_id": str(session.pk)}, operation_id=operation_id(session),
            idempotency_key=operation_id(session))
        if (not re.fullmatch(r"tok_[0-9a-f]{32}", refs.get("token_id", ""))
                or not isinstance(refs.get("credential_id"), str) or not 1 <= len(refs["credential_id"]) <= 160):
            raise ValidationError("广告授权保管结果无法确认，请联系管理员核对。")
        with transaction.atomic():
            session = load(actor, session_id, lock=True)
            if session.status != "exchanging":
                raise Conflict()
            session.credential_id, session.token_id = refs["credential_id"], refs["token_id"]
            session.status = "authorized"
            session.save(update_fields=["credential_id", "token_id", "status"])
            audit(session, actor, "authorized")
    except Exception:
        # Includes ambiguous exchange/custody outcomes. Never replay an exchange.
        AdsOAuthSession.objects.filter(pk=session_id, status="exchanging").update(status="unknown")
        audit(session, actor, "unknown", "failed")
        raise ValidationError("本次广告授权结果尚未确认。系统不会重复兑换，请刷新状态或联系管理员核对。") from None
    return discover(actor, session_id)


def operation_id(session):
    # The UUID and committed claim exist before any network call, including crashes.
    return "ads-" + str(session.pk)


def _references_owned(credential_id, token_id):
    from .models import MarketplaceStoreAuthorization
    # Disabled mappings and historical authorizations still own their references.
    references = Q(pk__in=[])
    if credential_id:
        references |= Q(credential_id=credential_id)
    if token_id:
        references |= Q(token_id=token_id)
    return (bool(token_id) and TikTokAdsAdvertiserMapping.objects.filter(token_id=token_id).exists()
        or MarketplaceStoreAuthorization.objects.filter(references).exists())


def cleanup_ads_authorizations(limit=50):
    """Fence expired/unbound attempts, close custody operations, then revoke or retry."""
    limit = max(0, min(int(limit), 100))
    now = timezone.now()
    eligible = Q(callback_transport="direct") & (Q(status__in=["cancelled", "cleanup_pending"])
        | Q(status__in=["authorized", "unknown"], expires_at__lte=now)
        | Q(status="exchanging", consumed_at__lte=now - timedelta(minutes=2))
        | Q(status="cleaning", cleanup_lease_until__lte=now))
    ids = list(AdsOAuthSession.objects.filter(eligible).order_by("expires_at", "pk")
        .values_list("pk", flat=True)[:limit])
    summary = {"claimed": 0, "cleaned": 0, "retry": 0, "owned": 0}
    for session_id in ids:
        with transaction.atomic():
            session = AdsOAuthSession.objects.select_for_update().filter(pk=session_id).filter(eligible).first()
            if session is None:
                continue
            fence = uuid.uuid4()
            session.status = "cleaning"
            session.cleanup_fence = fence
            session.cleanup_lease_until = timezone.now() + timedelta(minutes=5)
            session.cleanup_attempts += 1
            session.cleanup_error = ""
            session.save(update_fields=["status", "cleanup_fence", "cleanup_lease_until",
                "cleanup_attempts", "cleanup_error"])
            credential_id, token_id = session.credential_id, session.token_id
        summary["claimed"] += 1
        outcome, error = "retry", "CUSTODY_RECONCILIATION_PENDING"
        try:
            backend = custody()
            # close=True permanently tombstones even absent operations, fencing late stores.
            found = backend.lookup_reference_by_operation(operation_id(session), close=True)
            if not isinstance(found, dict) or type(found.get("found")) is not bool:
                raise ValueError("Unconfirmed operation closure")
            if found["found"]:
                recovered_credential, recovered_token = found.get("credential_id"), found.get("token_id")
                if (not isinstance(recovered_credential, str) or not 1 <= len(recovered_credential) <= 160
                        or not isinstance(recovered_token, str) or not re.fullmatch(r"tok_[0-9a-f]{32}", recovered_token)
                        or credential_id and credential_id != recovered_credential
                        or token_id and token_id != recovered_token):
                    raise ValueError("Operation references inconsistent")
                credential_id, token_id = recovered_credential, recovered_token
            with transaction.atomic():
                current = AdsOAuthSession.objects.select_for_update().get(pk=session_id)
                if current.status != "cleaning" or current.cleanup_fence != fence:
                    continue
                if current.cleanup_lease_until <= timezone.now():
                    continue
                current.credential_id, current.token_id = credential_id, token_id
                current.save(update_fields=["credential_id", "token_id"])
                owned = _references_owned(credential_id, token_id) if credential_id or token_id else False
            if owned:
                outcome, error = "owned", "REFERENCES_OWNED"
            elif not found["found"] and not credential_id and not token_id:
                outcome, error = "cleaned", ""
            elif not credential_id or not token_id:
                raise ValueError("Incomplete references")
            else:
                result = backend.revoke(credential_id, token_id)
                if not isinstance(result, dict) or result.get("status") != "revoked":
                    raise ValueError("Revocation unconfirmed")
                outcome, error = "cleaned", ""
        except Exception:
            pass
        updated = AdsOAuthSession.objects.filter(pk=session_id, status="cleaning", cleanup_fence=fence).update(
            status={"cleaned": "cleaned", "owned": "cleanup_owned", "retry": "cleanup_pending"}[outcome],
            cleanup_error=error, cleanup_lease_until=None)
        if updated:
            summary[outcome] += 1
    return summary


def discover(actor, session_id):
    session = load(actor, session_id)
    if session.status != "authorized" or not session.token_id:
        raise Conflict("请先完成广告授权，再发现账户；不要重复提交原回执。")
    try:
        backend = custody()
        token = backend.retrieve_access_token(session.token_id)
        secret = backend.retrieve_secret(session.integration_config.credential_id)
        data = request_json(session, "GET", HOST + "oauth2/advertiser/get/?" + urlencode({
            "app_id": str(session.integration_config.platform_config["app_id"]), "secret": secret}), token=token)
        rows = data.get("list")
        if not isinstance(rows, list) or len(rows) > MAX_CANDIDATES:
            raise ValueError
        candidates = []
        seen = set()
        for row in rows:
            identifier = str(row.get("advertiser_id", ""))
            if not re.fullmatch(r"[0-9]{1,64}", identifier) or identifier in seen:
                raise ValueError
            seen.add(identifier)
            candidates.append({"advertiser_id": identifier, "name": str(row.get("advertiser_name", ""))[:200],
                "verify_state": "unverified", "reason": "", "currency": "", "timezone": "", "verified_at": ""})
    except Exception:
        audit(session, actor, "discovery_failed", "failed")
        return {**sanitized(load(actor, session_id)), "discovery_failed": True}
    with transaction.atomic():
        current = load(actor, session_id, lock=True)
        if current.status != "authorized" or current.token_id != session.token_id:
            raise Conflict()
        previous = {c["advertiser_id"]: c for c in current.candidates}
        current.candidates = [previous.get(c["advertiser_id"], c) for c in candidates]
        current.save(update_fields=["candidates"])
        audit(current, actor, "discovered")
    return sanitized(current)


def account_timezone(account):
    # Numeric offsets cannot identify an IANA zone. Never infer from country/currency.
    for value in (account.get("display_timezone"), account.get("timezone")):
        if not isinstance(value, str) or not value or len(value) > 60:
            continue
        try:
            ZoneInfo(value)
            return value
        except (ValueError, KeyError):
            continue
    raise ValueError("No valid account timezone")


def verify(actor, session_id, advertiser_id):
    session = load(actor, session_id)
    if session.status != "authorized" or advertiser_id not in {c["advertiser_id"] for c in session.candidates}:
        raise Conflict("请选择本次授权发现的广告账户。")
    verified = {"verify_state": "failed", "reason": "account_verification_failed", "currency": "", "timezone": "", "verified_at": ""}
    try:
        data = request_json(session, "GET", HOST + "advertiser/info/?" + urlencode({"advertiser_ids": json.dumps([advertiser_id])}),
            token=custody().retrieve_access_token(session.token_id))
        rows = data.get("list")
        if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("advertiser_id")) != advertiser_id:
            raise ValueError
        row = rows[0]
        currency = row.get("currency", "")
        zone = account_timezone(row)
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError
        verified.update(verify_state="verified", reason="", currency=currency, timezone=zone,
            verified_at=timezone.now().isoformat())
    except Exception:
        pass
    with transaction.atomic():
        current = load(actor, session_id, lock=True)
        if current.status != "authorized" or current.token_id != session.token_id:
            raise Conflict()
        if advertiser_id not in {c["advertiser_id"] for c in current.candidates}:
            raise Conflict()
        current.candidates = [{**c, **verified} if c["advertiser_id"] == advertiser_id else c for c in current.candidates]
        current.save(update_fields=["candidates"])
        audit(current, actor, "verified" if verified["verify_state"] == "verified" else "verify_failed",
            "success" if verified["verify_state"] == "verified" else "failed")
    return sanitized(current)


def bind(actor, session_id, advertiser_ids, idempotency_key):
    request_hash = digest(json.dumps([sorted(advertiser_ids), idempotency_key], separators=(",", ":")))
    try:
        with transaction.atomic():
            session = load(actor, session_id, lock=True)
            if session.status == "bound":
                if session.binding_request_hash == request_hash:
                    return sanitized(session)
                raise Conflict()
            if session.status != "authorized" or not session.token_id:
                raise Conflict()
            candidates = {c["advertiser_id"]: c for c in session.candidates}
            if any(i not in candidates or candidates[i].get("verify_state") != "verified" for i in advertiser_ids):
                raise ValidationError("只能绑定本次授权中已验证的所选广告账户。")
            # Serializes all new Ads binds in this tenant, including absent rows.
            from apps.tenants.models import Tenant
            Tenant.objects.select_for_update().get(pk=session.tenant_id)
            existing = {m.advertiser_id: m for m in TikTokAdsAdvertiserMapping.objects.select_for_update().filter(
                tenant_id=session.tenant_id, advertiser_id__in=advertiser_ids)}
            if any(m.store_id != session.store_id or m.integration_config_id != session.integration_config_id
                    for m in existing.values()):
                raise Conflict()
            results = []
            for identifier in advertiser_ids:
                candidate = candidates[identifier]
                mapping = existing.get(identifier)
                if mapping is None:
                    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant_id=session.tenant_id, store_id=session.store_id,
                        integration_config_id=session.integration_config_id, advertiser_id=identifier, token_id=session.token_id,
                        currency=candidate["currency"], timezone=candidate["timezone"], enabled=False)
                else:
                    mapping.token_id = session.token_id
                    mapping.currency, mapping.timezone = candidate["currency"], candidate["timezone"]
                    mapping.enabled = False
                    mapping.save(update_fields=["token_id", "currency", "timezone", "enabled", "updated_at"])
                results.append({"mapping_id": mapping.pk, "advertiser_id": identifier})
            session.status, session.binding_request_hash, session.binding_results = "bound", request_hash, results
            session.save(update_fields=["status", "binding_request_hash", "binding_results"])
            audit(session, actor, "bound")
            return sanitized(session)
    except IntegrityError:
        raise Conflict() from None
