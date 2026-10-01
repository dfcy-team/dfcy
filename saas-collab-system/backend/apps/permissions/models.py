from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

from apps.tenants.models import Tenant


class Role(models.Model):
    class RoleType(models.TextChoices):
        BUILTIN = "builtin", "内置角色"
        TEMPLATE = "template", "角色模板"
        CUSTOM = "custom", "自定义角色"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=80)
    description = models.TextField(blank=True, default="")
    role_type = models.CharField(
        max_length=20,
        choices=RoleType.choices,
        default=RoleType.CUSTOM,
    )
    # A protected role remains assignable/configurable only through the
    # explicit safeguards in the system-management API.  This is deliberately
    # data-backed instead of inferred from a display name so role codes remain
    # stable when labels are localized or corrected.
    is_protected = models.BooleanField(default=False)
    permissions = models.ManyToManyField("Permission", blank=True, related_name="roles")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_role_code_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.code}"


class Permission(models.Model):
    class PermissionType(models.TextChoices):
        """The authorization surface a permission controls.

        ``action`` is the compatibility default for the permission catalog
        that predates the split model.  Menu and field grants are deliberately
        represented by the same catalog table so roles can be migrated
        incrementally without breaking the existing ``permissions`` M2M.
        """

        MENU = "menu", "Menu"
        ACTION = "action", "Action"
        FIELD = "field", "Field"

    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=100)
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    permission_type = models.CharField(
        max_length=20,
        choices=PermissionType.choices,
        default=PermissionType.ACTION,
    )
    # Route/field metadata is intentionally opaque JSON.  It is catalog data,
    # not user-provided credentials; API consumers can use it to render a
    # trusted menu/field directory without another authorization table.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["permission_type", "module", "action", "code"]

    def __str__(self):
        return self.code


class OrgMembership(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships")
    department = models.ForeignKey("tenants.Department", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="active", choices=Role.Status.choices)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user", "department"], name="uniq_org_membership")]

    def clean(self):
        if self.user.tenant_id != self.tenant_id or self.department.tenant_id != self.tenant_id:
            raise ValidationError("组织成员、部门和用户必须属于同一租户。")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class UserRole(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="user_roles")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")
    membership = models.ForeignKey(OrgMembership, on_delete=models.CASCADE, null=True, blank=True, related_name="role_bindings")
    context_key = models.CharField(max_length=80, default="tenant")
    source = models.CharField(max_length=80, default="legacy")
    status = models.CharField(max_length=20, default="active", choices=Role.Status.choices)
    valid_until = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_role_bindings")

    class Meta:
        ordering = ["tenant_id", "user_id", "role_id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user", "role", "context_key", "source"], name="uniq_role_binding_context"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.role_id}"

    def clean(self):
        if self.user.tenant_id != self.tenant_id or self.role.tenant_id != self.tenant_id:
            raise ValidationError("角色绑定与用户必须属于同一租户。")
        if self.membership_id:
            if self.membership.tenant_id != self.tenant_id or self.membership.user_id != self.user_id:
                raise ValidationError("组织成员不属于当前用户与租户。")
            if self.context_key != f"department:{self.membership.department_id}":
                raise ValidationError("组织绑定上下文不一致。")
        elif self.context_key != "tenant":
            raise ValidationError("租户级绑定必须使用 tenant 上下文。")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class RoleBinding(UserRole):
    """Version-compatible binding API; existing UserRole rows stay in place."""
    class Meta:
        proxy = True


class DataScope(models.Model):
    class ScopeType(models.TextChoices):
        # ``all`` is always tenant-local.  It never means platform-wide data.
        ALL = "all", "租户内全部数据"
        # These values remain readable for historical role records.  New
        # permission updates must use only ALL or CUSTOM (see the serializer).
        DEPARTMENT = "department", "历史组织范围（本部门）"
        DEPARTMENT_TREE = "department_tree", "历史组织范围（部门及下级）"
        OWN = "own", "历史组织范围（本人）"
        CUSTOM = "custom", "按业务范围限制"

    NEW_SCOPE_TYPES = frozenset({ScopeType.ALL, ScopeType.CUSTOM})
    LEGACY_SCOPE_TYPES = frozenset({ScopeType.DEPARTMENT, ScopeType.DEPARTMENT_TREE, ScopeType.OWN})
    # Business scope is intentionally limited to tenant-owned master-data
    # dimensions.  Organization/user/role keys are legacy scope metadata and
    # cannot be submitted by the new role-permission API.
    BUSINESS_SCOPE_KEYS = frozenset({
        "platform_ids", "site_ids", "store_ids", "warehouse_ids", "supplier_ids",
    })
    LEGACY_ORGANIZATION_SCOPE_KEYS = frozenset({"user_ids", "department_ids", "role_ids"})

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="data_scopes")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="data_scopes")
    scope_type = models.CharField(
        max_length=20,
        choices=ScopeType.choices,
        help_text="新配置只能使用租户内全部数据或按业务范围限制；历史组织范围仅兼容读取。",
    )
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["tenant_id", "role_id", "scope_type"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "role", "scope_type"], name="uniq_data_scope_per_role"),
        ]

    def __str__(self):
        return f"{self.role.code}:{self.scope_type}"


class RoleResourcePolicy(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="resource_policies")
    resource_code = models.CharField(max_length=120)
    permission_code = models.CharField(max_length=120, default="*")
    scope_type = models.CharField(max_length=20, choices=[("all", "租户内全部数据"), ("custom", "按业务范围限制")])
    config = models.JSONField(default=dict)
    schema_version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "role", "resource_code", "permission_code"], name="uniq_role_resource_policy")]

    def clean(self):
        from .resource_policies import validate_resource_policy
        if self.role.tenant_id != self.tenant_id:
            raise ValidationError("资源范围与角色必须属于同一租户。")
        self.config = validate_resource_policy(self.tenant_id, self.resource_code, self.scope_type, self.config)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class PermissionChange(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    batch_id = models.UUIDField(unique=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    reason = models.CharField(max_length=240)
    operation = models.CharField(max_length=40)
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
