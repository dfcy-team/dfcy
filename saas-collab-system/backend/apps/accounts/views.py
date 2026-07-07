from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import CurrentUserSerializer, InternalTokenObtainPairSerializer


def health_response(service):
    return Response({"status": "ok", "service": service})


@api_view(["GET"])
def internal_health(request):
    return health_response("internal")


@api_view(["GET"])
def external_health(request):
    return health_response("external")


class InternalLoginView(TokenObtainPairView):
    serializer_class = InternalTokenObtainPairSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def current_user(request):
    serializer = CurrentUserSerializer(request.user)
    return Response(serializer.data)


class ExternalLoginPlaceholderView(APIView):
    def post(self, request):
        return Response({"status": "not_implemented", "service": "external-auth"}, status=501)


class RPATokenPlaceholderView(APIView):
    def post(self, request):
        return Response({"status": "not_implemented", "service": "rpa-auth"}, status=501)
