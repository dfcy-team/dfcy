"""Self-service binding, independent from anonymous Feishu login handoffs."""

from datetime import timedelta
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.credential_auth import credential_lease_active
from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.common.responses import error_response, success_response
from apps.tenants.models import Tenant

from .custody import CustodyError
from .feishu_identity_service import FeishuIdentityService, OPEN_ID_PATTERN
from .feishu_login import (
    COOKIE_PATH, HANDOFF_TTL, STATE_TTL, FeishuOAuthClient,
    _configuration_digest, _configured_connection, _digest, _no_store,
    _same_origin, _set_cookie,
)
from .models import FeishuBindingSession, FeishuIdentity
from .oauth_errors import OAuthFlowError


STATE_PREFIX = "bind_"
BROWSER_COOKIE = "feishu_bind_browser"
HANDOFF_COOKIE = "feishu_bind_handoff"
MESSAGES = {
    "config_unavailable": "飞书扫码绑定暂不可用，请联系管理员。",
    "state_invalid": "绑定请求无效，请重新验证密码并扫码。",
    "expired": "绑定二维码已过期，请重新验证密码并扫码。",
    "denied": "飞书授权已取消，您可以重新扫码绑定。",
    "provider_error": "飞书认证暂未完成，请重新扫码。",
    "account_unavailable": "当前系统账号不可用于绑定，请联系管理员。",
    "password_invalid": "当前密码不正确，请重新输入。",
    "already_bound": "当前系统账号已有飞书绑定，如需变更请联系管理员。",
    "identity_in_use": "该飞书账号已绑定其他系统账号，请联系管理员。",
    "retry_required": "绑定暂未完成，请稍后重新验证密码并扫码。",
}


def _clear_cookies(response):
    for name in (BROWSER_COOKIE, HANDOFF_COOKIE):
        response.delete_cookie(name, path=COOKIE_PATH, samesite="Lax")
    return response


def _failure(code, status=400):
    return _no_store(error_response(code, MESSAGES[code], status=status))


def _callback_failure(code):
    return _clear_cookies(_no_store(HttpResponseRedirect(
        "/?" + urlencode({"feishu_binding_error": code}))))


def _valid_browser(request, session):
    nonce = request.COOKIES.get(BROWSER_COOKIE, "")
    return (bool(nonce) and len(nonce) <= 128
            and constant_time_compare(_digest(nonce), session.browser_digest))


def _valid_actor(user, connection, credential_digest=None):
    return bool(
        user and connection and user.tenant_id == connection.tenant_id
        and user.user_type == CustomUser.UserType.INTERNAL
        and user.tenant.status == Tenant.Status.ACTIVE
        and user.has_usable_password() and credential_lease_active(user)
        and (credential_digest is None
             or constant_time_compare(_digest(user.password), credential_digest))
    )


def _status(user, connection):
    # Any existing mapping prevents self-service replacement, including a stale
    # or disabled mapping. Do not expose provider identifiers or contact details.
    identity = FeishuIdentity.objects.filter(user_id=user.pk).order_by("pk").first()
    return {
        "enabled": _valid_actor(user, connection),
        "bound": identity is not None,
        "status": ("active" if identity.status == "active" and identity.open_id
                   and identity.tenant_id == user.tenant_id else "inactive") if identity else None,
        "bound_at": identity.created_at.isoformat() if identity else None,
        "username": user.username,
    }


def _current_actor(request):
    return CustomUser.objects.select_related("tenant").get(pk=request.user.pk)


class FeishuBindingThrottle(UserRateThrottle):
    scope = "feishu_binding"
    rate = "20/min"


class FeishuBindingPasswordThrottle(UserRateThrottle):
    scope = "feishu_binding_password"
    rate = "5/min"


class SelfFeishuBindingView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [FeishuBindingThrottle]


class FeishuBindingStatusView(SelfFeishuBindingView):
    def get(self, request):
        return _no_store(success_response(_status(_current_actor(request), _configured_connection(request))))


class FeishuBindingStartView(SelfFeishuBindingView):
    throttle_classes = [FeishuBindingPasswordThrottle]

    def post(self, request):
        if not _same_origin(request) or not isinstance(request.data, dict) or set(request.data) != {"current_password"}:
            return _failure("state_invalid", 403)
        connection, user = _configured_connection(request), _current_actor(request)
        if not connection:
            return _failure("config_unavailable", 503)
        if not _valid_actor(user, connection):
            return _failure("account_unavailable", 403)
        password = request.data.get("current_password")
        if not isinstance(password, str) or not password or len(password) > 1024 or not user.check_password(password):
            return _failure("password_invalid", 403)
        if FeishuIdentity.objects.filter(user_id=user.pk).exists():
            return _failure("already_bound", 409)
        now = timezone.now()
        stale = list(FeishuBindingSession.objects.filter(
            expires_at__lt=now - timedelta(days=1)).values_list("pk", flat=True)[:100])
        FeishuBindingSession.objects.filter(pk__in=stale).delete()
        # A new QR supersedes earlier intents for this user, including other tabs.
        FeishuBindingSession.objects.filter(user=user).exclude(stage__in=["consumed", "failed"]).update(
            stage="failed", open_id="")
        state, browser_nonce = STATE_PREFIX + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        FeishuBindingSession.objects.create(
            state_digest=_digest(state), browser_digest=_digest(browser_nonce),
            configuration_digest=_configuration_digest(connection),
            credential_digest=_digest(user.password), user=user, connection=connection,
            expires_at=now + timedelta(seconds=STATE_TTL),
        )
        authorize_url = "https://passport.feishu.cn/suite/passport/oauth/authorize?" + urlencode({
            "client_id": connection.app_id, "redirect_uri": settings.FEISHU_LOGIN_REDIRECT_URI,
            "response_type": "code", "state": state,
        })
        response = _no_store(success_response({"authorize_url": authorize_url, "expires_in": STATE_TTL}))
        response.delete_cookie(HANDOFF_COOKIE, path=COOKIE_PATH, samesite="Lax")
        _set_cookie(response, request, BROWSER_COOKIE, browser_nonce, STATE_TTL + HANDOFF_TTL)
        return response


def binding_callback(request, state):
    """OAuth authenticates Feishu only; authenticated completion writes the mapping."""
    session = FeishuBindingSession.objects.select_related("user", "user__tenant").filter(
        state_digest=_digest(state), stage="pending").first()
    if not session or not _valid_browser(request, session):
        return _callback_failure("state_invalid")
    if session.expires_at <= timezone.now():
        return _callback_failure("expired")
    connection = _configured_connection(request)
    if (not connection or connection.pk != session.connection_id
            or not constant_time_compare(session.configuration_digest, _configuration_digest(connection))):
        return _callback_failure("config_unavailable")
    if not _valid_actor(session.user, connection, session.credential_digest):
        return _callback_failure("account_unavailable")
    if FeishuBindingSession.objects.filter(pk=session.pk, stage="pending", expires_at__gt=timezone.now()).update(stage="processing") != 1:
        return _callback_failure("state_invalid")
    if request.query_params.get("error"):
        return _callback_failure("denied")
    code = request.query_params.get("code", "")
    if not code or len(code) > 2048:
        return _callback_failure("provider_error")
    try:
        open_id = FeishuOAuthClient().get_open_id(connection, code)
        if not isinstance(open_id, str) or len(open_id) > 120 or not OPEN_ID_PATTERN.fullmatch(open_id):
            return _callback_failure("provider_error")
        # Apply the administrator binding endpoint's organization access check.
        # OAuth alone must not bypass the configured tenant's contact boundary.
        FeishuIdentityService().find_candidate_by_open_id(connection=connection, open_id=open_id)
    except (CustodyError, OAuthFlowError, ValidationError, ValueError, TypeError):
        return _callback_failure("provider_error")
    handoff = secrets.token_urlsafe(32)
    if FeishuBindingSession.objects.filter(pk=session.pk, stage="processing").update(
        stage="ready", open_id=open_id, handoff_digest=_digest(handoff),
        expires_at=timezone.now() + timedelta(seconds=HANDOFF_TTL),
    ) != 1:
        return _callback_failure("state_invalid")
    response = _no_store(HttpResponseRedirect("/?feishu_binding=complete"))
    _set_cookie(response, request, HANDOFF_COOKIE, handoff, HANDOFF_TTL)
    return response


class FeishuBindingCompleteView(SelfFeishuBindingView):
    def post(self, request):
        if not _same_origin(request) or request.data:
            return _failure("state_invalid", 403)
        handoff = request.COOKIES.get(HANDOFF_COOKIE, "")
        if not handoff or len(handoff) > 128:
            return _clear_cookies(_failure("state_invalid"))
        try:
            response = self._complete(request, handoff)
        except IntegrityError:
            response = _failure("already_bound", 409)
        except OperationalError as exc:
            # Lock contention is retryable; don't expose DB diagnostics or lose
            # the existing binding. All other DB errors retain normal handling.
            if not exc.args or exc.args[0] not in {1205, 1213}:
                raise
            response = _failure("retry_required", 409)
        return _clear_cookies(_no_store(response))

    @staticmethod
    @transaction.atomic
    def _complete(request, handoff):
        # Use the same tenant lock as the administrator's binding endpoint so
        # competing users cannot pass the duplicate check simultaneously.
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        session = FeishuBindingSession.objects.select_for_update().filter(
            handoff_digest=_digest(handoff), stage="ready", user_id=request.user.pk).first()
        if not session or not _valid_browser(request, session):
            return _failure("state_invalid")
        code = None
        connection, user = _configured_connection(request), _current_actor(request)
        if session.expires_at <= timezone.now():
            code = "expired"
        elif (not connection or connection.pk != session.connection_id
              or not constant_time_compare(session.configuration_digest, _configuration_digest(connection))):
            code = "config_unavailable"
        elif not _valid_actor(user, connection, session.credential_digest):
            code = "account_unavailable"
        elif FeishuIdentity.objects.filter(user_id=user.pk).exists():
            code = "already_bound"
        elif FeishuIdentity.objects.filter(tenant_id=connection.tenant_id, open_id=session.open_id).exists():
            code = "identity_in_use"
        elif not OPEN_ID_PATTERN.fullmatch(session.open_id):
            code = "state_invalid"
        if code:
            session.stage, session.open_id = "failed", ""
            session.save(update_fields=["stage", "open_id"])
            return _failure(code, 409 if code in {"already_bound", "identity_in_use"} else 400)
        identity = FeishuIdentity.objects.create(tenant_id=user.tenant_id, user=user, open_id=session.open_id)
        session.stage, session.open_id = "consumed", ""
        session.save(update_fields=["stage", "open_id"])
        write_operation_log(
            tenant=user.tenant, user=user, module="accounts", action="feishu_self_bind",
            object_type="user", object_id=user.pk, after_data={"identity_id": identity.pk},
        )
        return success_response(_status(user, connection))
