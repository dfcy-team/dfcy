"""Redirect-based shared login; caller systems never receive user credentials."""

import base64
import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.accounts.credential_auth import credential_lease_active
from apps.accounts.models import CustomUser
from apps.common.responses import success_response

from .internal_readonly_api import _authenticate, _consume_limit
from .models import InternalAPIClient, InternalSSOAuthorizationCode


_PKCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_STATE_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")
_VERIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


def _eligible(client):
    return (
        client is not None
        and client.allow_sso_login
        and client.status == InternalAPIClient.Status.ACTIVE
        and client.approval_status == InternalAPIClient.ApprovalStatus.APPROVED
        and (client.expires_at is None or client.expires_at > timezone.now())
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def authorize(request):
    user = request.user
    if user.user_type != CustomUser.UserType.INTERNAL or not user.is_active or not credential_lease_active(user):
        return Response({"detail": "Shared login is unavailable."}, status=403)
    data = request.data if isinstance(request.data, dict) else {}
    client_id = data.get("client_id")
    redirect_uri = data.get("redirect_uri")
    state = data.get("state")
    challenge = data.get("code_challenge")
    if not all(isinstance(item, str) for item in (client_id, redirect_uri, state, challenge)):
        return Response({"detail": "Invalid authorization request."}, status=400)
    if not _STATE_PATTERN.fullmatch(state) or not _PKCE_PATTERN.fullmatch(challenge):
        return Response({"detail": "Invalid state or PKCE challenge."}, status=400)
    client = InternalAPIClient.objects.filter(client_id=client_id, tenant=user.tenant).first()
    if not _eligible(client) or redirect_uri not in client.sso_redirect_uris:
        return Response({"detail": "Shared login is unavailable for this callback."}, status=403)
    code = secrets.token_urlsafe(32)
    InternalSSOAuthorizationCode.objects.create(
        client=client,
        user=user,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        expires_at=timezone.now() + timedelta(seconds=90),
    )
    return success_response({"redirect_url": f"{redirect_uri}?{urlencode({'code': code, 'state': state})}"})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def exchange_token(request):
    client = _authenticate(request)
    if not _eligible(client):
        return Response({"detail": "Client authentication failed."}, status=401)
    if not _consume_limit(client):
        return Response({"detail": "Rate limit exceeded."}, status=429)
    data = request.data if isinstance(request.data, dict) else {}
    code = data.get("code")
    redirect_uri = data.get("redirect_uri")
    verifier = data.get("code_verifier")
    if not isinstance(code, str) or len(code) > 128 or not isinstance(redirect_uri, str) or not isinstance(verifier, str) or not _VERIFIER_PATTERN.fullmatch(verifier):
        return Response({"detail": "Invalid authorization code."}, status=400)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with transaction.atomic():
        grant = InternalSSOAuthorizationCode.objects.select_for_update().select_related("user").filter(code_hash=code_hash).first()
        if (
            grant is None or grant.client_id != client.id or grant.redirect_uri != redirect_uri
            or redirect_uri not in client.sso_redirect_uris
            or grant.consumed_at is not None or grant.expires_at <= timezone.now()
            or not secrets.compare_digest(grant.code_challenge, challenge)
        ):
            return Response({"detail": "Invalid authorization code."}, status=400)
        user = grant.user
        if user.tenant_id != client.tenant_id or user.user_type != CustomUser.UserType.INTERNAL or not user.is_active or not credential_lease_active(user):
            return Response({"detail": "Shared login is unavailable."}, status=403)
        grant.consumed_at = timezone.now()
        grant.save(update_fields=["consumed_at"])
    return success_response({"user_id": user.id, "username": user.username, "full_name": user.full_name, "tenant_id": user.tenant_id})
