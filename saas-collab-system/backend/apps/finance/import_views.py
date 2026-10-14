from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsFinanceImporter
from .imports import commit_upload, parse_upload, templates
from .models import FinanceAuditLog


@api_view(["GET", "POST"])
@permission_classes([IsFinanceImporter])
def finance_imports(request):
    if request.method == "GET":
        history = FinanceAuditLog.objects.filter(tenant=request.user.tenant, actor=request.user, action="import_finance_csv").order_by("-id")[:50]
        return success_response({"templates": templates(), "max_rows": 500, "max_bytes": 1024 * 1024, "history": [{"id": x.id, "created_at": x.created_at, **x.masked_detail} for x in history]})
    kind = request.data.get("kind")
    mode = request.data.get("mode", "preview")
    if mode == "preview":
        _, summary = parse_upload(request.user, kind, request.FILES.get("file"))
        return success_response(summary)
    if mode == "commit":
        result = commit_upload(request.user, kind, request.FILES.get("file"), request.data.get("sha256"))
        return success_response(result, status=201)
    raise ValidationError({"mode": "不支持的导入操作。"})
