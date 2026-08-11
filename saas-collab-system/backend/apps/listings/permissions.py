from apps.development.permissions import permission_class
from rest_framework.permissions import BasePermission
from apps.permissions.services import check_user_permission, get_permission_data_scopes


CanViewListings = permission_class("listings.profile.view")
CanManageListings = permission_class("listings.profile.manage")
CanApproveListings = permission_class("listings.profile.approve")
CanPublishListings = permission_class("listings.profile.publish")
CanViewTemplates = permission_class("listings.template.view")
CanManageTemplates = permission_class("listings.template.manage")


def any_permission_class(*codes):
    class AnyNamedPermission(BasePermission):
        permission_codes = codes

        def has_permission(self, request, view):
            user = request.user
            return bool(
                user and user.is_authenticated and user.is_active and user.user_type == "internal"
                and any(check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in self.permission_codes)
            )

    return AnyNamedPermission


# New granular codes are preferred; profile/template permissions remain a
# compatibility fallback for tenants seeded before the global-listing rollout.
CanViewListingMappings = any_permission_class("listings.mapping.view", "listings.profile.view")
CanManageListingMappings = any_permission_class("listings.mapping.manage", "listings.template.manage", "listings.profile.manage")
CanViewListingTasks = any_permission_class("listings.task.view", "listings.profile.view")
CanViewListingWorkbench = any_permission_class("listings.workbench.view", "listings.profile.view")
CanManageListingWorkbench = any_permission_class("listings.workbench.manage", "listings.profile.manage")
CanManageListingProduction = any_permission_class("listings.publish.production", "listings.profile.publish")
CanViewListingProfiles = any_permission_class("listings.profile.view", "listings.workbench.view", "listings.task.view")
CanManageListingProfiles = any_permission_class("listings.profile.manage", "listings.workbench.manage")
# New task-management permission is accepted for the publish endpoint while
# keeping the original profile.publish code valid for existing roles.
CanPublishListings = any_permission_class("listings.profile.publish", "listings.task.manage")
