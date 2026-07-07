from rest_framework.decorators import api_view
from rest_framework.response import Response


def health_response(service):
    return Response({"status": "ok", "service": service})


@api_view(["GET"])
def internal_health(request):
    return health_response("internal")


@api_view(["GET"])
def external_health(request):
    return health_response("external")
