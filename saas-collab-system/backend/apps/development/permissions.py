from rest_framework.permissions import BasePermission

from apps.permissions.services import check_user_permission, get_permission_data_scopes


def permission_class(code):
    class NamedPermission(BasePermission):
        permission_code = code

        def has_permission(self, request, view):
            user = request.user
            return bool(
                user
                and user.is_authenticated
                and user.is_active
                and user.user_type == "internal"
                and check_user_permission(user, self.permission_code)
                and get_permission_data_scopes(user, self.permission_code)
            )

    return NamedPermission


def any_permission_class(*codes):
    """Permission class for a capability shared by requirement/project roles."""

    class AnyNamedPermission(BasePermission):
        permission_codes = codes

        def has_permission(self, request, view):
            user = request.user
            if not (
                user
                and user.is_authenticated
                and user.is_active
                and user.user_type == "internal"
            ):
                return False
            return any(
                check_user_permission(user, code)
                and get_permission_data_scopes(user, code)
                for code in self.permission_codes
            )

    return AnyNamedPermission


CanViewProjects = permission_class("development.project.view")
CanManageProjects = permission_class("development.project.manage")
CanFinalizeProjects = permission_class("development.project.approve")
CanManageCosts = permission_class("development.cost.manage")
CanApproveCosts = permission_class("development.cost.approve")
CanImportSales = permission_class("development.sales.import")
CanViewSales = permission_class("development.sales.view")
CanReviewRequirements = permission_class("development.requirement.review")

# Archive actions are intentionally compatible with the existing product
# development roles.  Deployments that have not yet seeded the more granular
# archive permissions can still use their project permissions; newly seeded
# roles may grant the dedicated codes for least-privilege access.
CanViewProductArchives = any_permission_class(
    "development.product_archive.view",
    "development.project.view",
)
CanManageProductArchives = any_permission_class(
    "development.product_archive.manage",
    "development.project.manage",
)
# Trial SKU generation is a mutation of the virtual archive and therefore
# shares the archive-manage boundary; keep the explicit name for older API
# clients and route imports.
CanGenerateProductArchives = CanManageProductArchives
CanConfirmProductArchives = any_permission_class(
    "development.product_archive.confirm",
    "development.project.approve",
)

# Competitor reports are read-only upstream data.  Requirement viewers and
# product-project viewers may inspect them; creating/removing a link requires
# a requirement manage/review or project manage permission.
CanViewCompetitorReports = any_permission_class(
    "development.requirement.view",
    "development.project.view",
)
CanManageCompetitorLinks = any_permission_class(
    "development.requirement.manage",
    "development.requirement.review",
    "development.project.manage",
)
