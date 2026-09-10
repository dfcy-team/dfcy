"""Authenticated callback recovery without fetching a user-supplied URL."""
from urllib.parse import parse_qsl, urlsplit

from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsMarketplaceStoreAuthorizer
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .marketplace_oauth_service import complete_marketplace_oauth_callback
from .models import OAuthStateSession
from .oauth_state_service import oauth_state_digest
from .serializers import MarketplaceStoreAuthorizationSerializer


class ManualCallbackInput(serializers.Serializer):
    callback_url = serializers.CharField(max_length=8192, write_only=True)
    store_id = serializers.IntegerField(min_value=1)
    integration_config_id = serializers.IntegerField(min_value=1)


def validate_manual_callback(*, actor, callback_url, store_id, integration_config_id):
    try:
        url = urlsplit(callback_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError()
        pairs = parse_qsl(url.query, keep_blank_values=True, max_num_fields=40)
        params = dict(pairs)
        if len(params) != len(pairs) or not params.get("state"):
            raise ValueError()
    except ValueError:
        raise ValidationError("请粘贴包含 state 的完整 HTTPS 回调地址；不接受重复参数、账号信息或片段。") from None
    session = OAuthStateSession.objects.select_related("integration_config").filter(
        state_hash=oauth_state_digest(params["state"]), tenant_id=actor.tenant_id,
        initiated_by=actor, store_id=store_id, integration_config_id=integration_config_id,
    ).first()
    if session is None:
        raise ValidationError("回调不属于当前用户、店铺或接入配置，请重新发起授权。")
    config = session.integration_config
    if not integration_values_allowed(actor, "integrations.store.authorize", platform=session.platform,
            environment=config.environment, regions=[session.region], config_id=config.pk, store_id=session.store_id):
        raise PermissionDenied("当前店铺授权超出可操作数据范围。")
    expected = urlsplit(session.redirect_uri)
    if ((url.scheme, url.netloc, url.path) != (expected.scheme, expected.netloc, expected.path)
            or any(params.get(key) != value for key, value in parse_qsl(expected.query, keep_blank_values=True))):
        raise ValidationError("回调域名或路径与本次授权登记地址不一致。")
    return session.platform, params


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def manual_store_callback(request):
    serializer = ManualCallbackInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    platform, params = validate_manual_callback(actor=request.user, **serializer.validated_data)
    # Existing service atomically consumes state and checks expiry, platform,
    # provider parameters and the returned shop identity. No bypass or retry.
    authorization = complete_marketplace_oauth_callback(platform=platform, query_params=params)
    return success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)
