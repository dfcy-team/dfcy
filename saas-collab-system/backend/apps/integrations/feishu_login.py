"""Feishu QR OAuth -> existing internal account; no implicit account binding."""

from datetime import timedelta
import hashlib
import secrets
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.credential_auth import credential_lease_active
from apps.accounts.models import CustomUser
from apps.accounts.serializers import InternalTokenObtainPairSerializer
from apps.audit.services import write_operation_log
from apps.common.responses import error_response, success_response
from apps.tenants.models import Tenant

from .custody import CustodyError, get_custody_backend
from .feishu_identity_service import OPEN_ID_PATTERN
from .models import FeishuConnection, FeishuIdentity, FeishuLoginSession
from .net_guard import PlatformHttpClient
from .oauth_errors import OAuthFlowError


CALLBACK_PATH = "/api/feishu/login/callback/"
COOKIE_PATH = "/api/feishu/login/"
BROWSER_COOKIE = "feishu_login_browser"
HANDOFF_COOKIE = "feishu_login_handoff"
STATE_TTL = 300
HANDOFF_TTL = 60
MESSAGES = {
    "config_unavailable": "飞书扫码登录暂不可用，请使用账号密码登录。",
    "state_invalid": "扫码登录请求无效，请重新获取二维码。",
    "expired": "二维码已过期，请重新获取二维码。",
    "denied": "飞书授权已取消，可重新扫码或使用账号密码登录。",
    "provider_error": "飞书认证暂未完成，请重试或使用账号密码登录。",
    "unbound": "该飞书账号尚未绑定系统账号，请使用账号密码登录并联系管理员绑定。",
    "account_unavailable": "绑定的系统账号当前不可用，请联系管理员。",
}


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _configuration_digest(connection):
    return _digest("\n".join((str(connection.pk), connection.app_id, connection.app_secret_ref,
                              connection.domain, settings.FEISHU_LOGIN_REDIRECT_URI)))


def _identity_digest(identity):
    return _digest("\n".join((str(identity.pk), str(identity.tenant_id), str(identity.user_id),
                              identity.open_id, identity.status)))


def _configured_connection(request):
    app_id = settings.FEISHU_LOGIN_APP_ID
    uri = settings.FEISHU_LOGIN_REDIRECT_URI
    try:
        parsed = urlsplit(uri)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if (not app_id or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path != CALLBACK_PATH
                or origin != request.build_absolute_uri("/").rstrip("/")
                or (parsed.scheme != "https" and not (
                    settings.DEBUG and parsed.scheme == "http"
                    and parsed.hostname in {"localhost", "127.0.0.1", "testserver"}))):
            return None
    except ValueError:
        return None
    connections = list(FeishuConnection.objects.select_related("tenant").filter(
        app_id=app_id, enabled=True, domain="feishu", tenant__status=Tenant.Status.ACTIVE,
    ).exclude(app_secret_ref="")[:2])
    # App-specific open IDs must never select between ambiguous local tenants.
    return connections[0] if len(connections) == 1 else None


def _same_origin(request):
    origin = request.headers.get("Origin")
    return not origin or origin == request.build_absolute_uri("/").rstrip("/")


def _no_store(response):
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _set_cookie(response, request, name, value, age):
    response.set_cookie(name, value, max_age=age, path=COOKIE_PATH,
                        secure=request.is_secure(), httponly=True, samesite="Lax")


def _clear_cookies(response):
    for name in (BROWSER_COOKIE, HANDOFF_COOKIE):
        response.delete_cookie(name, path=COOKIE_PATH, samesite="Lax")
    return response


def _failure(code, status=400):
    return _no_store(error_response(code, MESSAGES[code], status=status))


def _callback_failure(code):
    return _clear_cookies(_no_store(HttpResponseRedirect(
        "/login?" + urlencode({"feishu_error": code}))))


def _valid_browser(request, session):
    nonce = request.COOKIES.get(BROWSER_COOKIE, "")
    return (bool(nonce) and len(nonce) <= 128
            and constant_time_compare(_digest(nonce), session.browser_digest))


def _valid_identity(identity, connection):
    if (not identity or identity.status != "active" or not identity.open_id
            or identity.tenant_id != connection.tenant_id
            or identity.user.tenant_id != connection.tenant_id):
        return False
    return (identity.user.user_type == CustomUser.UserType.INTERNAL
            and identity.user.tenant.status == Tenant.Status.ACTIVE
            and credential_lease_active(identity.user)
            and FeishuIdentity.objects.filter(tenant_id=connection.tenant_id,
                                               open_id=identity.open_id).count() == 1)


class FeishuLoginThrottle(AnonRateThrottle):
    scope = "feishu_login"
    rate = "20/min"


class PublicFeishuLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [FeishuLoginThrottle]


class FeishuLoginConfigView(PublicFeishuLoginView):
    def get(self, request):
        return _no_store(success_response({"enabled": bool(_configured_connection(request))}))


class FeishuLoginStartView(PublicFeishuLoginView):
    def post(self, request):
        if not _same_origin(request):
            return _failure("state_invalid", 403)
        connection = _configured_connection(request)
        if not connection:
            return _failure("config_unavailable", 503)
        now = timezone.now()
        stale = list(FeishuLoginSession.objects.filter(
            expires_at__lt=now - timedelta(days=1)).values_list("pk", flat=True)[:100])
        FeishuLoginSession.objects.filter(pk__in=stale).delete()
        state, browser_nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        FeishuLoginSession.objects.create(
            state_digest=_digest(state), browser_digest=_digest(browser_nonce),
            configuration_digest=_configuration_digest(connection), connection=connection,
            expires_at=now + timedelta(seconds=STATE_TTL),
        )
        # The current QR SDK requires the passport (v1) authorize URL. Its code
        # is exchanged with the supported v2 token endpoint below.
        authorize_url = "https://passport.feishu.cn/suite/passport/oauth/authorize?" + urlencode({
            "client_id": connection.app_id, "redirect_uri": settings.FEISHU_LOGIN_REDIRECT_URI,
            "response_type": "code", "state": state,
        })
        response = _no_store(success_response({"authorize_url": authorize_url, "expires_in": STATE_TTL}))
        response.delete_cookie(HANDOFF_COOKIE, path=COOKIE_PATH, samesite="Lax")
        _set_cookie(response, request, BROWSER_COOKIE, browser_nonce, STATE_TTL + HANDOFF_TTL)
        return response


class FeishuOAuthClient:
    def __init__(self):
        self.http = PlatformHttpClient(max_retries=0)

    @staticmethod
    def _payload(response):
        payload = response.json()
        if (not isinstance(payload, dict) or payload.get("code") not in (None, 0)
                or payload.get("error")):
            raise ValueError("Provider rejected login")
        return payload

    def get_open_id(self, connection, code):
        app_secret = get_custody_backend().retrieve_secret(connection.app_secret_ref)
        token = self._payload(self.http.request(
            "POST", "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
            json_body={"grant_type": "authorization_code", "client_id": connection.app_id,
                       "client_secret": app_secret, "code": code,
                       "redirect_uri": settings.FEISHU_LOGIN_REDIRECT_URI},
            retry=False, diagnostic_platform="feishu",
        )).get("access_token")
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise ValueError("Missing provider credential")
        profile = self._payload(self.http.request(
            "GET", "https://open.feishu.cn/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {token}"}, retry=False, diagnostic_platform="feishu",
        )).get("data")
        open_id = profile.get("open_id") if isinstance(profile, dict) else None
        if not isinstance(open_id, str) or not OPEN_ID_PATTERN.fullmatch(open_id):
            raise ValueError("Missing provider identity")
        return open_id


class FeishuLoginCallbackView(PublicFeishuLoginView):
    def get(self, request):
        state = request.query_params.get("state", "")
        if not state or len(state) > 128:
            return _callback_failure("state_invalid")
        session = FeishuLoginSession.objects.select_related("connection").filter(
            state_digest=_digest(state), stage="pending").first()
        if not session or not _valid_browser(request, session):
            return _callback_failure("state_invalid")
        if session.expires_at <= timezone.now():
            return _callback_failure("expired")
        connection = _configured_connection(request)
        if (not connection or connection.pk != session.connection_id
                or not constant_time_compare(session.configuration_digest, _configuration_digest(connection))):
            return _callback_failure("config_unavailable")
        # A conditional database update is atomic across workers, including
        # SQLite tests. A failed/uncertain provider exchange cannot reuse code.
        if FeishuLoginSession.objects.filter(pk=session.pk, stage="pending", expires_at__gt=timezone.now()).update(stage="processing") != 1:
            return _callback_failure("state_invalid")
        if request.query_params.get("error"):
            return _callback_failure("denied")
        code = request.query_params.get("code", "")
        if not code or len(code) > 2048:
            return _callback_failure("provider_error")
        try:
            open_id = FeishuOAuthClient().get_open_id(connection, code)
        except (CustodyError, OAuthFlowError, ValueError, TypeError):
            # Do not copy remote errors, auth codes or provider response bodies
            # into logs, responses or redirect URLs.
            return _callback_failure("provider_error")
        identities = list(FeishuIdentity.objects.select_related("user", "user__tenant").filter(
            tenant_id=connection.tenant_id, open_id=open_id)[:2])
        if not identities:
            return _callback_failure("unbound")
        identity = identities[0]
        if len(identities) != 1 or not _valid_identity(identity, connection):
            return _callback_failure("account_unavailable")
        handoff = secrets.token_urlsafe(32)
        FeishuLoginSession.objects.filter(pk=session.pk, stage="processing").update(
            identity=identity, stage="ready", handoff_digest=_digest(handoff),
            identity_digest=_identity_digest(identity),
            expires_at=timezone.now() + timedelta(seconds=HANDOFF_TTL),
        )
        response = _no_store(HttpResponseRedirect("/login?feishu=complete"))
        _set_cookie(response, request, HANDOFF_COOKIE, handoff, HANDOFF_TTL)
        return response


class FeishuLoginCompleteView(PublicFeishuLoginView):
    def post(self, request):
        if not _same_origin(request):
            return _failure("state_invalid", 403)
        handoff = request.COOKIES.get(HANDOFF_COOKIE, "")
        if not handoff or len(handoff) > 128:
            return _clear_cookies(_failure("state_invalid"))
        with transaction.atomic():
            session = FeishuLoginSession.objects.select_for_update().select_related(
                "identity", "identity__user", "identity__user__tenant").filter(
                handoff_digest=_digest(handoff), stage="ready").first()
            if not session or not _valid_browser(request, session):
                return _clear_cookies(_failure("state_invalid"))
            if session.expires_at <= timezone.now():
                return _clear_cookies(_failure("expired"))
            connection = _configured_connection(request)
            if (not connection or connection.pk != session.connection_id
                    or not constant_time_compare(session.configuration_digest, _configuration_digest(connection))):
                return _clear_cookies(_failure("config_unavailable"))
            if (not _valid_identity(session.identity, connection)
                    or not constant_time_compare(session.identity_digest, _identity_digest(session.identity))):
                return _clear_cookies(_failure("account_unavailable"))
            if FeishuLoginSession.objects.filter(pk=session.pk, stage="ready", expires_at__gt=timezone.now()).update(stage="consumed") != 1:
                return _clear_cookies(_failure("state_invalid"))
            user = session.identity.user
            refresh = InternalTokenObtainPairSerializer.get_token(user)
            write_operation_log(tenant=user.tenant, user=user, module="accounts", action="login",
                                object_type="user", object_id=user.pk, after_data={"method": "feishu"})
            response = success_response({"access": str(refresh.access_token), "refresh": str(refresh)})
        return _clear_cookies(_no_store(response))
