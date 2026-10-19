"""Authenticated completion of signed TK browser-relay receipts on the private SaaS."""
import os
from pathlib import Path
from urllib.parse import urlencode

from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import error_response, success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from apps.permissions.ui_p6_scopes import integration_values_allowed
from . import tiktok_bridge_protocol as protocol
from .models import OAuthStateSession, marketplace_authorization_api_type
from .oauth_errors import OAuthFlowError
from .oauth_state_service import oauth_state_digest
from .serializers import MarketplaceStoreAuthorizationSerializer


def bridge_key():
    filename = os.environ.get("TIKTOK_BROWSER_BRIDGE_KEY_FILE", "")
    if not filename:
        raise protocol.BridgeTokenError("BRIDGE_KEY_UNAVAILABLE")
    try:
        path = Path(filename)
        if not path.is_absolute() or not path.is_file() or path.stat().st_size > 4096:
            raise protocol.BridgeTokenError("BRIDGE_KEY_UNAVAILABLE")
        value = path.read_bytes().strip()
        if len(value) < 32:
            raise protocol.BridgeTokenError("BRIDGE_KEY_UNAVAILABLE")
        return value
    except OSError:
        raise protocol.BridgeTokenError("BRIDGE_KEY_UNAVAILABLE") from None


def prepare_browser_bridge(*, provider, session, state, authorization_url):
    if not os.environ.get("TIKTOK_BROWSER_BRIDGE_KEY_FILE"):
        return None
    try:
        if (session.platform != "tiktok" or marketplace_authorization_api_type(session.integration_config) != "marketplace"
                or not session.store.external_store_id):
            raise protocol.BridgeTokenError("BRIDGE_FLOW_INVALID")
        payload = {
            "session_id": session.pk, "state": state, "actor_id": session.initiated_by_id,
            "tenant_id": session.tenant_id, "store_id": session.store_id,
            "config_id": session.integration_config_id, "callback_uri": session.redirect_uri,
            "platform_store_id": session.store.external_store_id,
            "app_key": provider._app_id(), "region": session.region,
            "authorization_url": authorization_url, "return_uri": protocol.RETURN_URI,
        }
        protocol.validate_flow(payload)
        ttl = min(600, int((session.expires_at - timezone.now()).total_seconds()))
        ticket = protocol.sign_token(payload, bridge_key(), "start", ttl=ttl)
        # Fragment never reaches access logs; the relay page clears it before POST.
        return protocol.START_URI + "#" + urlencode({"ticket": ticket})
    except protocol.BridgeTokenError:
        raise ValidationError("TK 自动授权转接尚未就绪，请联系管理员核对独立转接配置。") from None


class BrowserReceiptInput(serializers.Serializer):
    receipt_token = serializers.CharField(max_length=25000, trim_whitespace=False, write_only=True)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) != {"receipt_token"}:
            raise ValidationError({"non_field_errors": ["TK 自动授权仅接受签名回执，请从原店铺重新发起。"]})
        return super().to_internal_value(data)


def validate_browser_receipt(*, actor, receipt_token):
    try:
        claims = protocol.verify_token(receipt_token, bridge_key(), "callback")
        protocol.validate_flow(claims)
        if (type(claims.get("flow_expires_at")) is not int
                or claims["exp"] > claims["flow_expires_at"]
                or claims["flow_expires_at"] <= int(timezone.now().timestamp())):
            raise protocol.BridgeTokenError("BRIDGE_FLOW_INVALID")
        params = claims.get("callback_params")
        if (not isinstance(params, dict) or set(params) - {"code", "state", "error", "app_key", "locale", "shop_region"}
                or any(not isinstance(v, str) or len(v) > 8192 or any(ord(c) < 32 or ord(c) == 127 for c in v) for v in params.values())
                or params.get("app_key") != claims["app_key"]
                or params.get("shop_region", "").upper() != claims["region"]
                or not (params.get("code", "").strip() or params.get("error", "").strip())
                or "state" in params and params["state"] != claims["state"]):
            raise protocol.BridgeTokenError("BRIDGE_FLOW_INVALID")
        if claims["actor_id"] != actor.pk or claims["tenant_id"] != actor.tenant_id:
            raise protocol.BridgeTokenError("BRIDGE_FLOW_INVALID")
        session = OAuthStateSession.objects.select_related("integration_config", "store__platform").filter(
            pk=claims["session_id"], state_hash=oauth_state_digest(claims["state"]),
            initiated_by=actor, tenant_id=actor.tenant_id, store_id=claims["store_id"],
            integration_config_id=claims["config_id"], platform="tiktok",
        ).first()
        if (session is None or session.redirect_uri != claims["callback_uri"] or session.region != claims["region"]
                or marketplace_authorization_api_type(session.integration_config) != "marketplace"
                or session.integration_config.platform != "tiktok"
                or session.store.tenant_id != actor.tenant_id or session.store.platform.platform_type != "tiktok"
                or session.store.external_store_id != claims["platform_store_id"]):
            raise protocol.BridgeTokenError("BRIDGE_FLOW_INVALID")
    except protocol.BridgeTokenError:
        raise ValidationError("TK 自动授权结果无效或已过期，请返回原店铺重新发起授权。") from None
    if not integration_values_allowed(actor, "integrations.store.authorize", platform="tiktok",
            environment=session.integration_config.environment, regions=[session.region],
            config_id=session.integration_config_id, store_id=session.store_id):
        raise PermissionDenied("当前店铺授权超出可操作数据范围。")
    return {**params, "state": claims["state"]}, claims["platform_store_id"]


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def complete_browser_authorization(request):
    serializer = BrowserReceiptInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    params, expected_store_id = validate_browser_receipt(actor=request.user, **serializer.validated_data)
    from .marketplace_oauth_service import complete_marketplace_oauth_callback
    try:
        # Legacy service flag enables strict selected-shop identity checks; this
        # path authenticates a relay receipt and never fakes manual confirmation.
        authorization = complete_marketplace_oauth_callback(
            platform="tiktok", query_params=params, tiktok_manual_recovery=True,
            tiktok_expected_store_id=expected_store_id)
    except OAuthFlowError as exc:
        return error_response(exc.error_code, f"OAuth flow rejected: {exc.controlled_code}",
            data={"reason_code": exc.controlled_code,
                  **({"diagnostic": exc.diagnostic} if hasattr(exc, "diagnostic") else {})}, status=exc.status_code)
    response = success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
