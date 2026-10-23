"""Same-SaaS TK Shop callback; the legacy relay is not a dependency."""
import hmac
import re
from urllib.parse import urlsplit

from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import error_response, success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from .models import OAuthStateSession, marketplace_authorization_api_type, oauth_state_service_write
from .oauth_errors import OAuthFlowError
from .oauth_state_service import oauth_state_digest, require_unchanged_configuration

CALLBACK_PATH = "/integrations/tiktok/shop-callback"
SALT = "tiktok-shop-direct-callback-v1"
PARAMS = {"code", "state", "error", "app_key", "locale", "shop_region"}


def configured_callback():
    from .tiktok_callback_settings import callback_setting
    value = callback_setting()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.path == CALLBACK_PATH
                 and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                 and "?" not in value and "#" not in value and "\\" not in value and "@" not in parsed.netloc
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and not any(ord(c) <= 32 or ord(c) == 127 for c in value))
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValidationError("TK 商城直连回调配置无效，请联系管理员；不会回退到其他服务器。")
    return value


def prepare_direct_callback(*, session, state, verifier):
    callback = configured_callback()
    if not callback or session.redirect_uri != callback:
        return None
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", verifier):
        raise ValidationError("TK 直连授权需要当前标签页的新会话，请刷新后重试。")
    with oauth_state_service_write():
        session.browser_verifier_hash = oauth_state_digest(verifier)
        session.callback_transport = "direct"
        session.save(update_fields=["browser_verifier_hash", "callback_transport"])
    claims = {
        "v": 1, "purpose": "tiktok_shop_direct", "transport": "direct",
        "session_id": session.pk, "actor_id": session.initiated_by_id, "tenant_id": session.tenant_id,
        "store_id": session.store_id, "config_id": session.integration_config_id,
        "platform_store_id": session.store.external_store_id, "platform_id": session.store.platform_id,
        "region": session.region, "callback_uri": callback, "state": state,
        "expires_at": int(session.expires_at.timestamp()),
    }
    return {"browser_token": signing.dumps(claims, salt=SALT), "callback_url": callback,
            "expires_at": session.expires_at}


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError("授权参数不受支持，请从原店铺重新发起。")
        return super().to_internal_value(data)


class DirectInput(StrictInput):
    browser_token = serializers.CharField(max_length=8192, trim_whitespace=False, write_only=True)
    browser_verifier = serializers.RegexField(r"^[A-Za-z0-9_-]{43,128}$", trim_whitespace=False, write_only=True)
    callback_params = serializers.JSONField(write_only=True)


def validate_direct_callback(*, actor, browser_token, browser_verifier, callback_params):
    from .marketplace_oauth_service import _require_callback_target_scope
    try:
        claims = signing.loads(browser_token, salt=SALT, max_age=600)
        if (not isinstance(claims, dict) or claims.get("v") != 1
                or claims.get("purpose") != "tiktok_shop_direct" or claims.get("transport") != "direct"
                or claims.get("actor_id") != actor.pk or claims.get("tenant_id") != actor.tenant_id
                or type(claims.get("expires_at")) is not int
                or claims["expires_at"] <= int(timezone.now().timestamp())
                or claims.get("callback_uri") != configured_callback()):
            raise ValueError()
        params = callback_params
        if (not isinstance(params, dict) or set(params) - PARAMS
                or any(not isinstance(v, str) or len(v) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in params.values())
                or not (params.get("code", "").strip() or params.get("error", "").strip())):
            raise ValueError()
        state_verified = "state" in params and params["state"] == claims.get("state")
        if "state" in params and not state_verified:
            raise ValueError()
        if not state_verified and not claims.get("platform_store_id"):
            from .oauth_errors import OAUTH_BINDING_IDENTITY_REQUIRED
            raise OAuthFlowError(OAUTH_BINDING_IDENTITY_REQUIRED)
        session = OAuthStateSession.objects.select_related("store__platform", "integration_config").filter(
            pk=claims.get("session_id"), state_hash=oauth_state_digest(claims.get("state")),
            initiated_by=actor, tenant_id=actor.tenant_id, store_id=claims.get("store_id"),
            integration_config_id=claims.get("config_id"), platform="tiktok", callback_transport="direct",
        ).first()
        if (session is None or session.expires_at <= timezone.now()
                or not session.browser_verifier_hash
                or not hmac.compare_digest(session.browser_verifier_hash, oauth_state_digest(browser_verifier))
                or session.redirect_uri != claims["callback_uri"] or session.region != claims.get("region")
                or session.store.platform_id != claims.get("platform_id")
                or session.store.external_store_id != claims.get("platform_store_id")
                or session.store.tenant_id != actor.tenant_id or session.store.platform.platform_type != "tiktok"
                or session.store.country_code.upper() != session.region.upper()
                or session.integration_config.platform != "tiktok"
                or marketplace_authorization_api_type(session.integration_config) != "marketplace"):
            raise ValueError()
        if not state_verified and (not params.get("app_key") or params.get("shop_region", "").upper() != session.region):
            raise ValueError()
        if "shop_region" in params and params["shop_region"].upper() != session.region.upper():
            raise ValueError()
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise ValidationError("TK 直连回调不属于当前会话或已过期，请从原店铺重新发起。") from None
    actor.refresh_from_db()
    if not actor.is_active or actor.user_type != "internal" or session.store.status != "active":
        raise PermissionDenied("当前账号或店铺不可继续授权。")
    require_unchanged_configuration(session)
    _require_callback_target_scope(session, store_id=session.store_id, integration_config=session.integration_config)
    return {**params, "state": claims["state"]}, claims["platform_store_id"], state_verified


def safe_response(data):
    response = success_response(data)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def failure_response(exc):
    response = error_response(exc.error_code, f"OAuth flow rejected: {exc.controlled_code}",
        data={"reason_code": exc.controlled_code,
              **({"diagnostic": exc.diagnostic} if hasattr(exc, "diagnostic") else {})}, status=exc.status_code)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@transaction.non_atomic_requests
@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def complete_direct_authorization(request):
    from .tiktok_shop_binding import start_shop_binding, complete_bound_shop_authorization
    serializer = DirectInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        params, expected_id, state_verified = validate_direct_callback(actor=request.user, **serializer.validated_data)
        if expected_id:
            result = complete_bound_shop_authorization(actor=request.user, query_params=params,
                expected_store_id=expected_id, callback_state_verified=state_verified)
        else:
            result = start_shop_binding(actor=request.user, query_params=params, callback_state_verified=state_verified)
    except OAuthFlowError as exc:
        return failure_response(exc)
    return safe_response(result)


class ConfirmInput(StrictInput):
    platform_store_id = serializers.RegexField(r"^[A-Za-z0-9_-]{1,128}$")


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def binding_status(request, binding_id):
    from .tiktok_shop_binding import get_binding
    try:
        return safe_response(get_binding(actor=request.user, binding_id=binding_id))
    except OAuthFlowError as exc:
        return failure_response(exc)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def binding_confirm(request, binding_id):
    from .tiktok_shop_binding import confirm_shop_binding
    serializer = ConfirmInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        return safe_response(confirm_shop_binding(actor=request.user, binding_id=binding_id, **serializer.validated_data))
    except OAuthFlowError as exc:
        return failure_response(exc)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def binding_cancel(request, binding_id):
    from .tiktok_shop_binding import cancel_shop_binding
    serializer = StrictInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        return safe_response(cancel_shop_binding(actor=request.user, binding_id=binding_id))
    except OAuthFlowError as exc:
        return failure_response(exc)
