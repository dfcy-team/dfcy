"""Authenticated callback recovery without fetching a user-supplied URL."""
from urllib.parse import parse_qsl, urlsplit

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.common.responses import error_response, success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .marketplace_oauth_service import complete_marketplace_oauth_callback
from .models import OAuthStateSession, marketplace_authorization_api_type
from .oauth_errors import OAuthFlowError
from .oauth_state_service import oauth_state_digest
from .oauth_diagnostics import callback_url_key
from .serializers import MarketplaceStoreAuthorizationSerializer


class ManualCallbackInput(serializers.Serializer):
    callback_url = serializers.CharField(max_length=8192, write_only=True)
    store_id = serializers.IntegerField(min_value=1)
    integration_config_id = serializers.IntegerField(min_value=1)
    tiktok_pending_token = serializers.CharField(max_length=256, write_only=True, required=False, trim_whitespace=False)
    tiktok_manual_confirmed = serializers.BooleanField(required=False, default=False, write_only=True)

    def validate(self, attrs):
        if {"tiktok_pending_token", "tiktok_manual_confirmed"}.intersection(self.initial_data):
            if not attrs.get("tiktok_pending_token") or attrs.get("tiktok_manual_confirmed") is not True:
                raise serializers.ValidationError("TikTok 手动恢复必须提供本次授权会话并明确确认。")
        return attrs


def validate_manual_callback(*, actor, callback_url, store_id, integration_config_id,
                             tiktok_pending_token=None, tiktok_manual_confirmed=False):
    try:
        url = urlsplit(callback_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError()
        pairs = parse_qsl(url.query, keep_blank_values=True, max_num_fields=40)
        params = dict(pairs)
        if len(params) != len(pairs) or any(ord(char) < 32 or ord(char) == 127 for char in callback_url):
            raise ValueError()
        recovery = "state" not in params
        if recovery:
            if not tiktok_pending_token or not tiktok_manual_confirmed or not str(params.get("code") or "").strip():
                raise ValueError()
        elif not params["state"] or tiktok_pending_token is not None or tiktok_manual_confirmed:
            raise ValueError()
    except ValueError:
        raise ValidationError("请粘贴包含 state 的完整 HTTPS 回调地址；不接受重复参数、账号信息或片段。") from None
    session = OAuthStateSession.objects.select_related("integration_config").filter(
        state_hash=oauth_state_digest(tiktok_pending_token if recovery else params["state"]), tenant_id=actor.tenant_id,
        initiated_by=actor, store_id=store_id, integration_config_id=integration_config_id,
    ).first()
    if session is None:
        raise ValidationError("回调不属于当前用户、店铺或接入配置，请重新发起授权。")
    config = session.integration_config
    if recovery:
        if (session.platform != "tiktok" or config.platform != "tiktok"
                or marketplace_authorization_api_type(config) != "marketplace"
                or session.status != OAuthStateSession.Status.PENDING or session.expires_at <= timezone.now()
                or not session.store_id or not session.store.external_store_id
                or session.store.tenant_id != actor.tenant_id or session.store.platform.platform_type != "tiktok"):
            raise ValidationError("仅支持当前用户刚发起且尚未使用的 TikTok 商城授权；请重新发起授权。")
    if not integration_values_allowed(actor, "integrations.store.authorize", platform=session.platform,
            environment=config.environment, regions=[session.region], config_id=config.pk, store_id=session.store_id):
        raise PermissionDenied("当前店铺授权超出可操作数据范围。")
    expected = urlsplit(session.redirect_uri)
    if (callback_url_key(callback_url)[:3] != callback_url_key(session.redirect_uri)[:3]
            or any(params.get(key) != value for key, value in parse_qsl(expected.query, keep_blank_values=True))):
        raise ValidationError("回调域名或路径与本次授权登记地址不一致。")
    if recovery:
        if (set(params) - {"code", "app_key", "locale", "shop_region"}
                or not params.get("app_key") or not params.get("shop_region")
                or str(params["shop_region"]).upper() != session.region.upper()):
            raise ValidationError("TikTok 回调缺少应用或站点信息，或包含不支持的参数。")
        params["state"] = tiktok_pending_token
    return session.platform, params


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def manual_store_callback(request):
    serializer = ManualCallbackInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    platform, params = validate_manual_callback(actor=request.user, **serializer.validated_data)
    # Existing service atomically consumes state and checks expiry, platform,
    # provider parameters and the returned shop identity. No bypass or retry.
    try:
        recovery_options = {"tiktok_manual_recovery": True} if serializer.validated_data.get("tiktok_pending_token") else {}
        authorization = complete_marketplace_oauth_callback(platform=platform, query_params=params, **recovery_options)
    except OAuthFlowError as exc:
        # Expose only the controlled reason, never provider details or the URL.
        # A consumed state remains a conflict, not an inferred success.
        return error_response(exc.error_code, f"OAuth flow rejected: {exc.controlled_code}",
                              data={"reason_code": exc.controlled_code,
                                    **({"diagnostic": exc.diagnostic} if hasattr(exc, "diagnostic") else {})},
                              status=exc.status_code)
    return success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)
