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
