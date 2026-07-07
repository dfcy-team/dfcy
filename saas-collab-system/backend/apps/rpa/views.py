from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.response import Response

from apps.permissions.api_permissions import IsRPAAgent


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "rpa"})


def placeholder_response(action, task_id=None):
    data = {"status": "ok", "service": "rpa", "action": action}
    if task_id is not None:
        data["task_id"] = task_id
    return Response(data)


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def claim_task(request):
    return placeholder_response("claim")


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def task_heartbeat(request, task_id):
    return placeholder_response("heartbeat", task_id)


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def append_task_log(request, task_id):
    return placeholder_response("logs", task_id)


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def complete_task(request, task_id):
    return placeholder_response("complete", task_id)


@api_view(["POST"])
@permission_classes([IsRPAAgent])
def fail_task(request, task_id):
    return placeholder_response("fail", task_id)
