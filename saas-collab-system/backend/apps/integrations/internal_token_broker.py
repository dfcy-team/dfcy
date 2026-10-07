"""Purpose-bound access-token handoff for one approved internal TikTok caller."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.responses import success_response
from apps.common.module_gate import is_module_enabled

from .custody import get_custody_backend
from .internal_readonly_api import _authenticate, _consume_limit
from .models import MarketplaceStoreAuthorization, TikTokTokenLeaseAudit
from .production_settings import get_runtime_platform_config, get_runtime_setting


def _reply(payload, status=200):
    response = payload if isinstance(payload, Response) else Response(payload, status=status)
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    response["Vary"] = "Authorization"
    return response


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def tiktok_shop_access_token(request):
    if not request.is_secure():
        return _reply({"detail": "Secure transport required."}, 403)
    client = _authenticate(request)
    if (client is None or client.tiktok_token_store_id is None or client.resources or client.allow_sso_login
            or client.caller_type != client.CallerType.INTERNAL_SYSTEM):
        return _reply({"detail": "Access denied."}, 403)
    if not _consume_limit(client):
        return _reply({"detail": "Rate limit exceeded."}, 429)
    store = client.tiktok_token_store
    if (store.tenant_id != client.tenant_id or store.code not in {"TK1PH", "TKKJ1PH"}
            or store.platform.platform_type != "tiktok"):
        return _reply({"detail": "Store binding unavailable."}, 403)
    settings = get_runtime_platform_config("tiktok")
    if (not settings.get("access_handoff_approved", False) or not settings.get("contract_approved", False)
            or not is_module_enabled("api_integrations")
            or not get_runtime_setting("network", "readonly_sync_enabled", default=False)):
        return _reply({"detail": "Token handoff is not approved."}, 403)
    records = list(MarketplaceStoreAuthorization.objects.select_related("integration_config").filter(
        tenant_id=client.tenant_id, store_id=store.id, platform="tiktok", status="active",
    )[:2])
    if len(records) != 1:
        return _reply({"detail": "Exactly one active shop authorization is required."}, 409)
    authorization = records[0]
    binding = {
        "tenant_id": client.tenant_id, "store_code": store.code,
        "region": authorization.region, "platform_store_id": authorization.platform_store_id,
    }
    if binding not in (settings.get("auto_refresh_bindings") or []):
        return _reply({"detail": "Shop is not in the approved pilot."}, 403)
    config = authorization.integration_config
    app_key = str(settings.get("app_id") or "").strip()
    if (config.environment not in {"pilot", "production"} or config.status not in {"verified", "active"}
            or not config.network_enabled or not config.sync_read_enabled or config.sync_write_enabled
            or authorization.last_error_code or not authorization.token_id or not authorization.expires_at
            or not app_key or not authorization.shop_cipher
            or authorization.expires_at <= timezone.now() + timedelta(minutes=2)):
        return _reply({"detail": "Shop token is unavailable; check SaaS renewal state."}, 503)
    try:
        access_token = get_custody_backend().retrieve_access_token(authorization.token_id)
    except Exception:
        return _reply({"detail": "Token custody is unavailable."}, 503)
    if not isinstance(access_token, str) or not access_token:
        return _reply({"detail": "Token custody is unavailable."}, 503)
    TikTokTokenLeaseAudit.objects.create(
        tenant_id=client.tenant_id, client=client, authorization=authorization,
        token_expires_at=authorization.expires_at,
    )
    return _reply(success_response({
        "store_code": store.code,
        "app_key": app_key,
        "shop_cipher": authorization.shop_cipher,
        "access_token": access_token,
        "expires_at": authorization.expires_at.isoformat(),
    }))
