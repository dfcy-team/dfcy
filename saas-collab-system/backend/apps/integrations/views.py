from rest_framework.decorators import api_view
from rest_framework.response import Response


def health_response(service):
    return Response({"status": "ok", "service": service})


@api_view(["GET"])
def platform_health(request):
    return health_response("platform")


@api_view(["GET"])
def wechat_health(request):
    return health_response("wechat")


@api_view(["GET"])
def feishu_health(request):
    return health_response("feishu")
