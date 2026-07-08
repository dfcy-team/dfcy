from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceUser


@api_view(["GET"])
@permission_classes([IsFinanceUser])
def health(request):
    return success_response({"status": "ok", "service": "finance"})
