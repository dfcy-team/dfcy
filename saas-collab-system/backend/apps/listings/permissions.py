from apps.development.permissions import permission_class


CanViewListings = permission_class("listings.profile.view")
CanManageListings = permission_class("listings.profile.manage")
CanApproveListings = permission_class("listings.profile.approve")
CanPublishListings = permission_class("listings.profile.publish")
CanViewTemplates = permission_class("listings.template.view")
CanManageTemplates = permission_class("listings.template.manage")
