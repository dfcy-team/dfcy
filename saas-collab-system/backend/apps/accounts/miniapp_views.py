from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import success_response

from .miniapp_auth import (
    authenticate_miniapp_code,
    issue_miniapp_tokens,
    refresh_miniapp_tokens,
)
from .miniapp_permissions import IsMiniAppToken
from .miniapp_serializers import (
    MiniAppCurrentUserSerializer,
    MiniAppLoginSerializer,
    MiniAppRefreshSerializer,
)


class MiniAppHealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        mode = settings.MINIAPP_AUTH_MODE
        return success_response(
            {
                "service": "miniapp-auth",
                "capability_status": mode if mode in {"sandbox", "platform"} else "disabled",
                "provider_exchange": (
                    "wechat-code2session"
                    if mode == "platform"
                    else "mock-only"
                    if mode == "sandbox"
                    else "disabled"
                ),
            }
        )


class MiniAppLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MiniAppLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate_miniapp_code(serializer.validated_data["code"])
        payload = issue_miniapp_tokens(user)
        payload["user"] = MiniAppCurrentUserSerializer(user).data
        return success_response(payload)


class MiniAppRefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MiniAppRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return success_response(refresh_miniapp_tokens(serializer.validated_data["refresh_token"]))


class MiniAppCurrentUserView(APIView):
    permission_classes = [IsAuthenticated, IsMiniAppToken]

    def get(self, request):
        return success_response(MiniAppCurrentUserSerializer(request.user).data)
