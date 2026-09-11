"""Warehouse-owned OMS bootstrap credentials; never shared-config tokens."""

from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .custody import get_custody_backend
from .models import PlatformIntegrationConfig, SyncJob, WarehouseAuthorization
from .net_guard import PlatformHttpClient
from .oauth_errors import OAuthFlowError


def invalidate_config_warehouses(config):
    records = WarehouseAuthorization.objects.filter(integration_config=config, provider="jifeng_wms", status="active")
    records.exclude(validation_status="incomplete").update(validation_status="pending", last_verified_at=None)
    SyncJob.objects.filter(warehouse_authorization__in=records).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)


def require_verified_warehouse(record):
    if record.provider != "jifeng_wms":
        return
    missing = []
    if not record.email:
        missing.append("Email")
    if not record.bootstrap_credential_id:
        missing.append("一次性授权 Token")
    if not record.oauth_user_id or not record.token_id:
        missing.append("首次授权")
    if not record.external_warehouse_code:
        missing.append("服务商外部仓库编码")
    if missing:
        raise ValidationError("仓库授权待补充：" + "、".join(missing))
    if record.validation_status != "verified" or not record.last_verified_at:
        raise ValidationError("仓库尚未通过只读连接校验，不能启用库存同步。")


@transaction.atomic
def save_warehouse_credentials(*, actor, authorization, email, token="", custody=None):
    record = WarehouseAuthorization.objects.select_for_update().get(
        pk=authorization.pk, tenant_id=actor.tenant_id,
    )
    if record.provider != "jifeng_wms" or record.status != WarehouseAuthorization.Status.ACTIVE:
        raise ValidationError("仅启用的极风仓库授权可以维护 OMS 凭据。")
    email = str(email or "").strip()
    if not isinstance(token, str) or len(token) > 4096 or (token and not token.strip()):
        raise ValidationError({"token": "Token 不能为空白字符或超过 4096 字符。"})
    try:
        validate_email(email)
    except DjangoValidationError:
        raise ValidationError({"email": "请填写有效的 OMS 账号邮箱。"}) from None
    if not record.bootstrap_credential_id and not token:
        raise ValidationError({"token": "首次配置必须填写 OMS 一次性授权 Token。"})
    if email != record.email and record.bootstrap_consumed_at and not token:
        raise ValidationError({"token": "更换已授权邮箱时必须提供新的 OMS 一次性授权 Token。"})
    if email == record.email and not token:
        return record
    if token:
        # Store as secret, never as access_token. Existing file/HTTP custody
        # encrypts it and returns an opaque reference. No raw value is audited.
        try:
            metadata = (custody or get_custody_backend()).store_secrets(
                secret=token,
                metadata={"tenant_id": actor.tenant_id, "warehouse_binding_id": record.pk},
            )
        except OAuthFlowError:
            raise ValidationError("仓库凭据加密保存失败，原配置未更改。") from None
        reference = metadata.get("credential_id")
        if not isinstance(reference, str) or not reference:
            raise ValidationError("仓库凭据托管未返回有效引用，保存失败。")
        record.bootstrap_credential_id = reference
        record.bootstrap_consumed_at = None
    record.email = email
    record.oauth_user_id = ""
    record.oauth_expires_at = None
    # Invalidate the old OAuth identity without revoking shared legacy refs.
    record.token_id = ""
    record.last_verified_at = None
    record.last_error_code = ""
    record.validation_status = WarehouseAuthorization.ValidationStatus.PENDING
    record.updated_by = actor
    record.save(update_fields=[
        "email", "bootstrap_credential_id", "bootstrap_consumed_at", "oauth_user_id",
        "oauth_expires_at", "token_id", "last_verified_at", "last_error_code",
        "validation_status", "updated_by", "updated_at",
    ])
    SyncJob.objects.filter(tenant_id=actor.tenant_id, warehouse_authorization=record).update(
        is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None,
    )
    return record


def jifeng_api_url(base_url, path):
    """Accept either a host or a host ending in /api, never duplicate /api."""
    parsed = urlsplit(str(base_url or "").strip())
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") not in ("", "/api")):
        raise ValidationError("API Base URL 必须是 HTTPS 域名，可带 /api，不能包含账号或查询参数。")
    return f"https://{parsed.netloc}{path}"


def authorize_warehouse(*, actor, authorization, http=None, custody=None):
    """Consume the one-use token once; a timeout must never cause a replay.

    The consumption marker is committed before the request. Failed/ambiguous
    authorization requires a replacement OMS token, not an automatic retry.
    """
    from .readonly_clients import JifengWmsReadonlyClient

    custody = custody or get_custody_backend()
    client = JifengWmsReadonlyClient(authorization.integration_config, authorization,
        http_client=http if http is not None else PlatformHttpClient(max_retries=0), custody=custody)
    client.preflight()
    config = authorization.integration_config
    base_url = config.platform_config.get("api_host")
    url = jifeng_api_url(base_url, "/api/oauth/authorize")
    domain = str(config.platform_config.get("domain") or "").strip()
    client_id = str(config.platform_config.get("client_id") or "").strip()
    if not domain or not client_id or not config.credential_id:
        raise ValidationError("公共配置缺少 Domain、Client ID 或 Client Secret。")
    secret = custody.retrieve_secret(config.credential_id)
    with transaction.atomic():
        record = WarehouseAuthorization.objects.select_for_update().get(pk=authorization.pk, tenant_id=actor.tenant_id)
        if record.provider != "jifeng_wms" or record.status != WarehouseAuthorization.Status.ACTIVE:
            raise ValidationError("极风仓库授权未启用。")
        if not record.email or not record.bootstrap_credential_id:
            raise ValidationError("请先补充仓库 Email 和一次性授权 Token。")
        if record.bootstrap_consumed_at:
            raise ValidationError("一次性 Token 已使用或曾尝试授权；请先更换新 Token。")
        token = custody.retrieve_secret(record.bootstrap_credential_id)
        record.bootstrap_consumed_at = timezone.now()
        record.last_verified_at = None
        record.validation_status = WarehouseAuthorization.ValidationStatus.PENDING
        record.save(update_fields=["bootstrap_consumed_at", "last_verified_at", "validation_status", "updated_at"])
        reference = record.bootstrap_credential_id
    try:
        def request(endpoint, params):
            response = client.http.request(
                "GET", endpoint + "?" + urlencode(params),
                connect_timeout=config.connect_timeout_seconds, read_timeout=config.read_timeout_seconds,
            )
            payload = response.json()
            if response.status_code != 200 or not isinstance(payload, dict) or str(payload.get("code")) != "0":
                raise ValueError("rejected")
            return payload.get("data")

        key = request(url, {"domain": domain, "clientId": client_id, "email": record.email, "token": token})
        if not isinstance(key, str) or not key:
            raise ValueError("missing authorization code")
        data = request(jifeng_api_url(base_url, "/api/oauth/accessToken"), {
            "clientId": client_id, "clientSecret": secret, "key": key,
        })
        if not isinstance(data, dict) or not all(data.get(k) for k in ("accessToken", "refreshToken", "userId")):
            raise ValueError("invalid authorization response")
        # The documentation does not specify the unit of expireIn. Do not
        # guess a timestamp: its API guide explicitly defines a 24h lifetime.
        expires_at = timezone.now() + timedelta(hours=24)
        metadata = custody.store_secrets(
            access_token=data["accessToken"], refresh_token=data["refreshToken"],
            metadata={"tenant_id": record.tenant_id, "warehouse_binding_id": record.pk},
        )
        if not metadata.get("token_id"):
            raise ValueError("missing custody reference")
        with transaction.atomic():
            live_config = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk)
            current = WarehouseAuthorization.objects.select_for_update().get(pk=record.pk)
            if (live_config.config_version != config.config_version or current.bootstrap_credential_id != reference
                    or current.status != WarehouseAuthorization.Status.ACTIVE):
                raise ValueError("credentials changed")
            current.token_id = metadata["token_id"]
            current.oauth_user_id = str(data["userId"])
            current.oauth_expires_at = expires_at
            current.last_error_code = ""
            current.authorized_at = timezone.now()
            current.save(update_fields=["token_id", "oauth_user_id", "oauth_expires_at", "last_error_code", "authorized_at", "updated_at"])
        return current
    except Exception:
        WarehouseAuthorization.objects.filter(pk=record.pk, bootstrap_credential_id=reference).update(
            validation_status=WarehouseAuthorization.ValidationStatus.FAILED,
            last_verified_at=None, last_error_code="JIFENG_AUTHORIZATION_FAILED",
        )
        raise ValidationError("极风授权未完成（认证拒绝、网络异常或凭据托管失败）。请检查公共配置并更换一次性 Token；不会自动重试。") from None


@transaction.atomic
def refresh_warehouse_authorization(*, actor, authorization, http=None, custody=None):
    """Explicit refresh uses warehouse OAuth credentials, never the OMS token."""
    from .readonly_clients import JifengWmsReadonlyClient

    config = PlatformIntegrationConfig.objects.select_for_update().get(pk=authorization.integration_config_id, tenant_id=actor.tenant_id)
    record = WarehouseAuthorization.objects.select_for_update().get(pk=authorization.pk, tenant_id=actor.tenant_id)
    if record.provider != "jifeng_wms" or record.status != "active" or not record.oauth_user_id or not record.token_id:
        raise ValidationError("请先完成该仓库的首次授权。")
    custody = custody or get_custody_backend()
    client = JifengWmsReadonlyClient(config, record,
        http_client=http if http is not None else PlatformHttpClient(max_retries=0), custody=custody)
    client.preflight()
    endpoint = jifeng_api_url(config.platform_config.get("api_host"), "/api/oauth/refreshToken")
    client_id = str(config.platform_config.get("client_id") or "").strip()
    if not client_id or not config.credential_id:
        raise ValidationError("公共配置缺少 Client ID 或 Client Secret。")
    try:
        response = client.http.request("GET", endpoint + "?" + urlencode({
            "clientId": client_id, "clientSecret": custody.retrieve_secret(config.credential_id),
            "refreshToken": custody.retrieve_refresh_token(record.token_id), "userId": record.oauth_user_id,
        }), connect_timeout=config.connect_timeout_seconds, read_timeout=config.read_timeout_seconds)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if (response.status_code != 200 or str(payload.get("code")) != "0" or not isinstance(data, dict)
                or not all(data.get(key) for key in ("accessToken", "refreshToken", "userId"))
                or str(data["userId"]) != record.oauth_user_id):
            raise ValueError("invalid refresh response")
        metadata = custody.store_secrets(access_token=data["accessToken"], refresh_token=data["refreshToken"],
            metadata={"tenant_id": actor.tenant_id, "warehouse_binding_id": record.pk})
        if not metadata.get("token_id"):
            raise ValueError("missing custody reference")
    except Exception:
        raise ValidationError("刷新授权失败，请检查网络及公共配置；若刷新凭据已失效，请更换 OMS Token 后重新授权。") from None
    record.token_id = metadata["token_id"]
    record.oauth_expires_at = timezone.now() + timedelta(hours=24)
    record.validation_status = "pending"
    record.last_verified_at = None
    record.last_error_code = ""
    record.save(update_fields=["token_id", "oauth_expires_at", "validation_status", "last_verified_at", "last_error_code", "updated_at"])
    SyncJob.objects.filter(warehouse_authorization=record).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
    return record
