"""JWT authentication with the UAT credential lease guard."""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .credential_auth import require_credential_lease
from .external_auth import SUPPLIER_WEB_TOKEN_CHANNEL, validate_supplier_web_access


class UATAwareJWTAuthentication(JWTAuthentication):
    """Preserve SimpleJWT behavior while rejecting expired UAT leases."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        require_credential_lease(user)
        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        membership_id = request.headers.get("X-Org-Membership")
        if membership_id:
            from django.db.models import Q
            from django.utils import timezone
            from apps.permissions.models import OrgMembership
            if not str(membership_id).isdigit() or not OrgMembership.objects.filter(
                pk=int(membership_id), user=user, tenant_id=user.tenant_id, status="active", department__status="active",
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=timezone.now())).exists():
                raise AuthenticationFailed("组织成员上下文无效或不属于当前用户。")
            user._active_membership_id = int(membership_id)
        if token.get("channel") == SUPPLIER_WEB_TOKEN_CHANNEL:
            path = str(getattr(request, "path", "") or "")
            if not (
                path.startswith("/api/external/supplier/")
                or path.startswith("/api/external/auth/")
            ):
                raise AuthenticationFailed(
                    "A supplier web token cannot access this API channel."
                )
            validate_supplier_web_access(user, token)
        return result
