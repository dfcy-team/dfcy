from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit.services import write_operation_log
from apps.common.responses import error_response, success_response

from .models import CustomUser
from .serializers import (
    CurrentUserSerializer,
    CurrentUserPasswordChangeSerializer,
    CurrentUserProfileSerializer,
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


class CurrentUserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response(CurrentUserProfileSerializer(request.user).data)

    @transaction.atomic
    def patch(self, request):
        user = CustomUser.objects.select_for_update().get(pk=request.user.pk)
        serializer = CurrentUserProfileSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        fields = ("full_name", "email", "phone")
        before_data = {field: getattr(user, field) for field in fields}
        user = serializer.save()
        after_data = {field: getattr(user, field) for field in fields}
        if before_data != after_data:
            write_operation_log(
                tenant=user.tenant,
                user=user,
                module="accounts",
                action="profile_update",
                object_type="user",
                object_id=user.pk,
                before_data=before_data,
                after_data=after_data,
            )
        return success_response(CurrentUserProfileSerializer(user).data)


class CurrentUserPasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = CustomUser.objects.select_for_update().get(pk=request.user.pk)
        serializer = CurrentUserPasswordChangeSerializer(
            data=request.data,
            context={"request": request, "user": user},
        )
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        write_operation_log(
            tenant=user.tenant,
            user=user,
            module="accounts",
            action="password_change",
            object_type="user",
            object_id=user.pk,
            after_data={"username": user.username, "changed": True},
        )
        return success_response({"password_changed": True})


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
