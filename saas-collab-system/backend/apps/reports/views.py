from rest_framework.decorators import api_view

from apps.common.responses import success_response


@api_view(["GET"])
def health(request):
    return success_response({"status": "ok", "service": "report"})
