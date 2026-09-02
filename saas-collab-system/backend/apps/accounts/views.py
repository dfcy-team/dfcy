from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.common.responses import error_response, success_response

from .serializers import (
    CurrentUserSerializer,
    InternalTokenObtainPairSerializer,
    SupplierWebTokenObtainPairSerializer,
    SupplierWebTokenRefreshSerializer,
    UATAwareTokenRefreshSerializer,
)


def health_response(service):
    return success_response({"status": "ok", "service": service})


@api_view(["GET"])
def internal_health(request):
    return health_response("internal")


@api_view(["GET"])
def external_health(request):
    return health_response("external")


class InternalLoginView(TokenObtainPairView):
    serializer_class = InternalTokenObtainPairSerializer


class InternalTokenRefreshView(TokenRefreshView):
    serializer_class = UATAwareTokenRefreshSerializer


class SupplierWebLoginView(TokenObtainPairView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SupplierWebTokenObtainPairSerializer


class SupplierWebRefreshView(TokenRefreshView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SupplierWebTokenRefreshSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request):
    serializer = CurrentUserSerializer(request.user)
    return success_response(serializer.data)


class ExternalLoginPlaceholderView(APIView):
    def post(self, request):
        return error_response(
            "NOT_IMPLEMENTED",
            "external auth is not implemented in stage 0",
            {"service": "external-auth"},
            status=501,
        )


class RPATokenPlaceholderView(APIView):
    def post(self, request):
        return error_response(
            "NOT_IMPLEMENTED",
            "rpa token auth is not implemented in stage 0",
            {"service": "rpa-auth"},
            status=501,
        )
