from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import InternalLoginView, current_user, internal_health
from .system_views import (
    DepartmentCollectionView,
    PermissionCollectionView,
    RoleCollectionView,
    RolePermissionView,
    SecurityOperationsView,
    UserCollectionView,
    UserRoleOptionCollectionView,
    UserRoleView,
    UserStatusView,
)


urlpatterns = [
    path("health/", internal_health, name="internal-health"),
    path("auth/login/", InternalLoginView.as_view(), name="internal-auth-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="internal-auth-refresh"),
    path("auth/me/", current_user, name="internal-auth-me"),
    path("system/departments/", DepartmentCollectionView.as_view(), name="system-department-collection"),
    path("system/users/", UserCollectionView.as_view(), name="system-user-collection"),
    path("system/users/<int:pk>/status/", UserStatusView.as_view(), name="system-user-status"),
    path("system/users/<int:pk>/roles/", UserRoleView.as_view(), name="system-user-roles"),
    path("system/user-role-options/", UserRoleOptionCollectionView.as_view(), name="system-user-role-options"),
    path("system/roles/", RoleCollectionView.as_view(), name="system-role-collection"),
    path("system/roles/<int:pk>/permissions/", RolePermissionView.as_view(), name="system-role-permissions"),
    path("system/permissions/", PermissionCollectionView.as_view(), name="system-permission-collection"),
    path("system/security-operations/", SecurityOperationsView.as_view(), name="system-security-operations"),
]
