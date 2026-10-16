from django.db import transaction
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p2_scopes import require_all_scope

from .archive_code_rules import all_rule_data, save_rule_data


class ArchiveCodeRuleView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "masterdata.settings.view"
    write_permission_code = "masterdata.settings.manage"

    def get(self, request):
        return success_response({"rules": all_rule_data(request.user.tenant)})

    @transaction.atomic
    def put(self, request):
        require_all_scope(request.user, self.write_permission_code)
        before = all_rule_data(request.user.tenant)
        after = save_rule_data(request.user.tenant, request.data.get("rules"))
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="masterdata",
            action="update", object_type="archive_code_rules", object_id=request.user.tenant_id,
            before_data={"rules": before}, after_data={"rules": after},
        )
        return success_response({"rules": after})
