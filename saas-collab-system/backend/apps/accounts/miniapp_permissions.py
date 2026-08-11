from rest_framework.permissions import BasePermission

from .miniapp_auth import MINIAPP_TOKEN_CHANNEL


class IsMiniAppToken(BasePermission):
    message = "A Mini Program channel token is required."

    def has_permission(self, request, view):
        token = request.auth
        return bool(token and token.get("channel") == MINIAPP_TOKEN_CHANNEL)
