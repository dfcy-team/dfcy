"""Bounded supplier-web authentication for the local supply-flow APIs.

The generic external login placeholder remains disabled.  This module exposes
only the explicitly scoped ``supplier_web`` channel and derives every supplier
claim from the current database binding on each login/refresh/access check.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.tenants.models import Tenant

from .credential_auth import require_credential_lease
from .models import CustomUser, ExternalUserProfile


SUPPLIER_WEB_TOKEN_CHANNEL = "supplier_web"


def _fail(message: str):
    raise AuthenticationFailed(message, code="supplier_auth_unavailable")


def resolve_supplier_web_binding(user):
    """Return the sole active supplier binding for an external user.

    The profile relation is checked explicitly rather than trusting a token or
    the profile's integer supplier id.  This keeps tenant/supplier changes
    fail-closed for both refresh and access authentication.
    """

    if user is None or not bool(getattr(user, "is_active", False)):
        _fail("The supplier account is unavailable.")
    if getattr(user, "user_type", None) != CustomUser.UserType.EXTERNAL:
        _fail("Only an external supplier account may use this channel.")
    tenant = Tenant.objects.filter(pk=user.tenant_id, status=Tenant.Status.ACTIVE).first()
    if tenant is None:
        _fail("The supplier tenant is unavailable.")
    profiles = list(ExternalUserProfile.objects.filter(user_id=user.pk)[:2])
    if len(profiles) != 1:
        _fail("A unique supplier binding is required.")
    profile = profiles[0]
    if profile.tenant_id != tenant.id or not profile.supplier_id:
        _fail("The supplier binding is inconsistent.")
    supplier = SupplierMaster.objects.filter(
        pk=profile.supplier_id,
        tenant_id=tenant.id,
        status=StatusChoices.ACTIVE,
    ).first()
    if supplier is None:
        _fail("The supplier account is not bound to an active supplier.")
    return tenant, profile, supplier


def stamp_supplier_web_claims(token, *, tenant_id: int, supplier_id: int):
    token["channel"] = SUPPLIER_WEB_TOKEN_CHANNEL
    token["tenant_id"] = int(tenant_id)
    token["supplier_id"] = int(supplier_id)
    token["user_type"] = CustomUser.UserType.EXTERNAL
    return token


def validate_supplier_web_claims(refresh: RefreshToken):
    """Validate a signed refresh token against the current binding."""

    if refresh.get("channel") != SUPPLIER_WEB_TOKEN_CHANNEL:
        _fail("The refresh token is not valid for the supplier web channel.")
    user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
    try:
        user_id = int(user_id)
        tenant_id = int(refresh.get("tenant_id"))
        supplier_id = int(refresh.get("supplier_id"))
    except (TypeError, ValueError):
        _fail("The supplier refresh token claims are invalid.")
    if user_id <= 0 or tenant_id <= 0 or supplier_id <= 0:
        _fail("The supplier refresh token claims are invalid.")
    user = get_user_model().objects.select_related("tenant").filter(pk=user_id).first()
    if user is None:
        _fail("The supplier account is unavailable.")
    tenant, profile, supplier = resolve_supplier_web_binding(user)
    if tenant.id != tenant_id or int(profile.supplier_id) != supplier_id:
        _fail("The supplier refresh token binding is stale.")
    require_credential_lease(user)
    return user, tenant, supplier


def validate_supplier_web_access(user, token):
    """Validate supplier-web access claims after JWT authentication."""

    if token.get("channel") != SUPPLIER_WEB_TOKEN_CHANNEL:
        return
    tenant, profile, supplier = resolve_supplier_web_binding(user)
    try:
        tenant_id = int(token.get("tenant_id"))
        supplier_id = int(token.get("supplier_id"))
    except (TypeError, ValueError):
        _fail("The supplier access token claims are invalid.")
    if tenant_id != tenant.id or supplier_id != int(profile.supplier_id):
        _fail("The supplier access token binding is stale.")


def issue_supplier_web_tokens(user):
    """Issue one signed supplier-web refresh/access pair."""

    tenant, profile, supplier = resolve_supplier_web_binding(user)
    require_credential_lease(user)
    refresh = stamp_supplier_web_claims(
        RefreshToken.for_user(user), tenant_id=tenant.id, supplier_id=profile.supplier_id
    )
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def refresh_supplier_web_tokens(refresh: RefreshToken):
    """Validate and derive a fresh access token from a supplier refresh token."""

    validate_supplier_web_claims(refresh)
    return {"access": str(refresh.access_token)}
