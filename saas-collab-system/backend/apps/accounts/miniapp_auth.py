import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation

from .credential_auth import credential_lease_active
from .models import CustomUser, MiniAppIdentity


MINIAPP_TOKEN_CHANNEL = "miniapp"
WECHAT_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
INVALID_WECHAT_CODE_ERRORS = {40029, 40163}


def digest_miniapp_subject(provider, subject):
    normalized = f"{provider}:{subject}".encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _invalid_code():
    return ContractViolation(
        "The Mini Program login code is invalid.",
        error_code=ErrorCode.MINIAPP_CODE_INVALID,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _provider_unavailable():
    return ContractViolation(
        "The WeChat identity provider is temporarily unavailable.",
        error_code=ErrorCode.MINIAPP_PROVIDER_UNAVAILABLE,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _fetch_wechat_session(code):
    query = urlencode(
        {
            "appid": settings.MINIAPP_APP_ID,
            "secret": settings.MINIAPP_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        with urlopen(
            f"{WECHAT_CODE2SESSION_URL}?{query}",
            timeout=settings.MINIAPP_PROVIDER_TIMEOUT_SECONDS,
        ) as response:
            raw_payload = response.read(16_385)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise _provider_unavailable() from exc
    if len(raw_payload) > 16_384:
        raise _provider_unavailable()
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _provider_unavailable() from exc
    if not isinstance(payload, dict):
        raise _provider_unavailable()
    return payload


def _exchange_wechat_code(code):
    if not settings.MINIAPP_APP_ID or not settings.MINIAPP_APP_SECRET:
        raise ContractViolation(
            "Mini Program platform credentials are not configured.",
            error_code=ErrorCode.MINIAPP_AUTH_DISABLED,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    payload = _fetch_wechat_session(code)
    error_code = payload.get("errcode")
    if error_code:
        if error_code in INVALID_WECHAT_CODE_ERRORS:
            raise _invalid_code()
        raise _provider_unavailable()
    openid = payload.get("openid")
    if not isinstance(openid, str) or not 3 <= len(openid) <= 200:
        raise _provider_unavailable()
    return MiniAppIdentity.Provider.WECHAT, openid


def exchange_login_code(code):
    mode = settings.MINIAPP_AUTH_MODE
    if mode == "disabled":
        raise ContractViolation(
            "Mini Program authentication is disabled.",
            error_code=ErrorCode.MINIAPP_AUTH_DISABLED,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if mode == "platform":
        if not isinstance(code, str) or not 3 <= len(code) <= 512:
            raise _invalid_code()
        return _exchange_wechat_code(code)
    if mode != "sandbox" or not code.startswith("sandbox:"):
        raise _invalid_code()
    subject = code.removeprefix("sandbox:").strip()
    if len(subject) < 3 or len(subject) > 200:
        raise _invalid_code()
    return MiniAppIdentity.Provider.WECHAT, subject


def authenticate_miniapp_code(code):
    provider, subject = exchange_login_code(code)
    subject_digest = digest_miniapp_subject(provider, subject)
    identity = (
        MiniAppIdentity.objects.select_related("user", "user__tenant")
        .filter(
            provider=provider,
            subject_digest=subject_digest,
            status=MiniAppIdentity.Status.ACTIVE,
            user__is_active=True,
        )
        .first()
    )
    if identity is None or identity.user.user_type == CustomUser.UserType.RPA or not credential_lease_active(identity.user):
        raise ContractViolation(
            "The Mini Program identity is not bound or is unavailable.",
            error_code=ErrorCode.MINIAPP_IDENTITY_UNBOUND,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    identity.last_login_at = timezone.now()
    identity.save(update_fields=["last_login_at", "updated_at"])
    return identity.user


def issue_miniapp_tokens(user):
    if not credential_lease_active(user):
        raise ContractViolation(
            "The Mini Program user credential is unavailable.",
            error_code=ErrorCode.MINIAPP_TOKEN_INVALID,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    refresh = RefreshToken.for_user(user)
    refresh["channel"] = MINIAPP_TOKEN_CHANNEL
    refresh["tenant_id"] = user.tenant_id
    refresh["user_type"] = user.user_type
    access = refresh.access_token
    expires_in = int(access.lifetime.total_seconds())
    return {
        "access_token": str(access),
        "refresh_token": str(refresh),
        "expires_in": expires_in,
        "expires_at": timezone.now() + access.lifetime,
    }


def refresh_miniapp_tokens(refresh):
    if refresh.get("channel") != MINIAPP_TOKEN_CHANNEL:
        raise ContractViolation(
            "The refresh token is not valid for the Mini Program channel.",
            error_code=ErrorCode.MINIAPP_TOKEN_INVALID,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    user = (
        CustomUser.objects.select_related("tenant")
        .filter(pk=refresh.get("user_id"), is_active=True)
        .exclude(user_type=CustomUser.UserType.RPA)
        .first()
    )
    if user is None:
        raise ContractViolation(
            "The Mini Program user is unavailable.",
            error_code=ErrorCode.MINIAPP_TOKEN_INVALID,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not credential_lease_active(user):
        raise ContractViolation(
            "The Mini Program user credential is unavailable.",
            error_code=ErrorCode.MINIAPP_TOKEN_INVALID,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    access = refresh.access_token
    expires_in = int(access.lifetime.total_seconds())
    return {
        "access_token": str(access),
        "refresh_token": str(refresh),
        "expires_in": expires_in,
        "expires_at": timezone.now() + access.lifetime,
    }
