"""Request gate for the opt-in shared Demo snapshot runtime."""
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed


def _error(status, code, message):
    return JsonResponse({"success": False, "code": code, "message": message, "data": None}, status=status)


class SharedDemoGateMiddleware:
    """Require a current, allowlisted internal superuser for every API route."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path == "/admin" or path.startswith("/admin/"):
            return _error(403, "PERMISSION_DENIED", "Admin site is unavailable in the shared Demo runtime.")

        is_api = path == "/api" or path.startswith("/api/")
        if is_api and path != "/api/internal/health/":
            marker = Path(settings.DEMO_SHARED_MAINTENANCE_FILE)
            if marker.is_file():
                return _error(503, "MAINTENANCE", "Shared Demo is temporarily unavailable.")

            if path not in {"/api/internal/auth/login/", "/api/internal/auth/refresh/"}:
                from apps.accounts.authentication import UATAwareJWTAuthentication

                try:
                    authenticated = UATAwareJWTAuthentication().authenticate(request)
                except AuthenticationFailed:
                    return _error(401, "AUTH_REQUIRED", "Authentication is required.")
                if authenticated is None:
                    return _error(401, "AUTH_REQUIRED", "Authentication is required.")

                user, _token = authenticated
                if not (
                    user.is_active
                    and user.user_type == "internal"
                    and user.is_superuser
                    and user.pk in settings.DEMO_SHARED_ADMIN_IDS
                ):
                    return _error(403, "PERMISSION_DENIED", "This account cannot access the shared Demo runtime.")

        return self.get_response(request)
