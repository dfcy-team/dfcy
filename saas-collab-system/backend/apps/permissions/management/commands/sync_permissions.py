import json

from django.core.management.base import BaseCommand, CommandError

from apps.permissions.catalog import permission_defaults, runtime_permission_definitions
from apps.permissions.menu_registry import MenuRegistryError
from apps.permissions.lifecycle import inactive_permissions, permission_is_effective
from apps.permissions.models import DataScope, Permission, Role
from apps.permissions.role_catalog import (
    BUILTIN_ROLE_DESCRIPTIONS,
    BUILTIN_ROLE_DISPLAY_NAMES,
    TENANT_ADMIN_ROLE_CODE,
)
MENU_REGISTRY_SOURCE = "frontend/src/router/menu.js"


def _menu_status(metadata):
    metadata = metadata or {}
    return metadata.get("registry_status", metadata.get("status", "active"))


def _role_refs(permission):
    return list(
        permission.roles.order_by("tenant_id", "code").values_list("tenant_id", "code")
    )


def _format_role_refs(refs):
    return ",".join(f"tenant={tenant_id}/role={code}" for tenant_id, code in refs) or "none"


def _action_can_open_menu(role, menu_code, action_code):
    """A warehouse-only mapping grant does not expose platform product rows."""
    if (menu_code, action_code) != (
        "menu.listings.products_platform_details.view", "integrations.product_mapping.view",
    ):
        return True
    scopes = role.data_scopes.all()
    return not scopes or any(
        scope.scope_type != DataScope.ScopeType.CUSTOM
        or not isinstance(scope.config, dict)
        or not ({"warehouse_ids", "supplier_ids"} & set(scope.config))
        for scope in scopes
    )


class Command(BaseCommand):
    help = "Synchronize the action, field and frontend-registered menu permission catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="只读检查登记源、权限目录、数据库和角色菜单授权漂移；有问题时非零退出。",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只预览将要同步的新增、修改、停用和补授，不写入数据库；有漂移时非零退出。",
        )
        parser.add_argument(
            "--report-json", action="store_true",
            help="输出目录残留与失效授权的聚合 JSON，异常样本最多 20 项。配合 --check/--dry-run 只读使用。",
        )
        parser.add_argument(
            "--strict-orphans", action="store_true",
            help="将尚未登记的有效操作/字段权限纳入漂移失败；先审阅历史迁移残留再启用此闸门。",
        )

    def handle(self, *args, **options):
        readonly = bool(options["check"] or options["dry_run"])
        try:
            definitions = tuple(runtime_permission_definitions())
        except MenuRegistryError as exc:
            raise CommandError(f"菜单登记源不可用：{exc}") from exc

        issues = []
        definitions_by_code = {}
        for definition in definitions:
            code = definition.get("code")
            if not code:
                issues.append("registry:missing-code")
                continue
            if code in definitions_by_code:
                issues.append(f"registry:duplicate:{code}")
                continue
            definitions_by_code[code] = definition
            if definition.get("permission_type") == Permission.PermissionType.MENU:
                metadata = definition.get("metadata") or {}
                if metadata.get("registry_collision"):
                    issues.append(f"registry:collision:{code}")
                if not metadata.get("path"):
                    issues.append(f"registry:menu-without-path:{code}")

        # The source declaration is authoritative for menu rows.  Legacy menu
        # rows not present in it are handled below as retired, never deleted.
        menu_definitions = {
            code: definition
            for code, definition in definitions_by_code.items()
            if definition.get("permission_type") == Permission.PermissionType.MENU
        }

        # Unregistered actions/fields need owner review, not automatic deletion
        # or retirement. Explicitly retired rows remain valid audit history.
        orphan_permissions = Permission.objects.filter(
            permission_type__in=(Permission.PermissionType.ACTION, Permission.PermissionType.FIELD),
        ).exclude(code__in=definitions_by_code)
        orphan_count = orphan_permissions.count()
        active_orphans = orphan_permissions.exclude(pk__in=inactive_permissions().values("pk"))
        active_orphan_count = active_orphans.count()
        if active_orphan_count:
            samples = ",".join(active_orphans.order_by("code").values_list("code", flat=True)[:20])
            if options["strict_orphans"]:
                issues.append(f"orphan_permissions:active={active_orphan_count}:samples={samples}")
            if not readonly:
                self.stdout.write(self.style.WARNING(
                    f"发现 {active_orphan_count} 项未登记操作/字段权限，已保留权限和角色关联，请审阅：{samples}"
                ))

        touched = 0
        created = 0
        repaired = 0
        retired = 0
        for code, definition in definitions_by_code.items():
            defaults = permission_defaults(definition)
            permission = Permission.objects.filter(code=code).first()
            if permission is None:
                issues.append(f"missing:{code}")
                if not readonly:
                    Permission.objects.create(code=code, **defaults)
                    created += 1
                continue

            stale_fields = [
                field for field, value in defaults.items()
                if getattr(permission, field) != value
            ]
            if stale_fields:
                issues.append(f"stale:{code}:{','.join(stale_fields)}")
                if not readonly:
                    for field, value in defaults.items():
                        setattr(permission, field, value)
                    permission.save(update_fields=list(defaults))
                    repaired += 1
            if stale_fields or _menu_status(getattr(permission, "metadata", {})) != "active":
                touched += 1

        # A route removed from the source is intentionally retained so stable
        # codes and historical role grants remain auditable.  Mark it inactive
        # in managed metadata and report every role still carrying the grant.
        for permission in Permission.objects.filter(permission_type=Permission.PermissionType.MENU):
            if permission.code in menu_definitions:
                continue
            metadata = dict(permission.metadata or {})
            if permission_is_effective(metadata) or metadata.get("registry_source") != MENU_REGISTRY_SOURCE:
                issues.append(f"retired_menu:{permission.code}:roles={_format_role_refs(_role_refs(permission))}")
                metadata.update({
                    "registry_source": MENU_REGISTRY_SOURCE,
                    "registry_status": "inactive",
                    "status": "inactive",
                })
                if not readonly:
                    permission.metadata = metadata
                    permission.save(update_fields=["metadata"])
                    retired += 1

        # Preserve visibility for existing roles during the menu/action split.
        # A role that already has any of a menu's declared action codes receives
        # the menu grant as an additive migration.  This also covers a new menu
        # added in a later release; no existing action or menu grant is removed.
        active_menu_rows = {
            code: Permission.objects.filter(code=code).first()
            for code in menu_definitions
        }
        for role in Role.objects.prefetch_related("permissions", "data_scopes"):
            role_permissions = list(role.permissions.all())
            current_codes = {permission.code for permission in role_permissions}
            action_codes = {
                permission.code
                for permission in role_permissions
                if permission.permission_type == Permission.PermissionType.ACTION
            }
            missing_menu_codes = []
            for code, definition in menu_definitions.items():
                permission = active_menu_rows.get(code)
                if permission is None:
                    continue
                metadata = definition.get("metadata") or {}
                if _menu_status(metadata) != "active":
                    continue
                required_actions = set(metadata.get("action_codes") or [])
                if permission.code not in current_codes and any(
                    _action_can_open_menu(role, code, action_code)
                    for action_code in required_actions & action_codes
                ):
                    missing_menu_codes.append(permission.code)
            if missing_menu_codes:
                issue = (
                    f"role_menu_missing:tenant={role.tenant_id}/role={role.code}:"
                    f"{','.join(sorted(missing_menu_codes))}"
                )
                issues.append(issue)
                if not readonly:
                    role.permissions.add(*Permission.objects.filter(code__in=missing_menu_codes))

        # The tenant administrator is a catalog-managed role.  New permission
        # definitions must be granted to it automatically; retired menu rows
        # remain attached as historical grants and are not revoked.
        # Employee delegation fields require an explicit role grant even for
        # tenant administrators. Preserve already reviewed grants on sync.
        all_permissions = Permission.objects.exclude(code__startswith="field.employee_readonly.")
        for role in Role.objects.filter(code=TENANT_ADMIN_ROLE_CODE):
            current_codes = set(role.permissions.values_list("code", flat=True))
            reviewed_employee_fields = role.permissions.filter(code__startswith="field.employee_readonly.")
            role_catalog = all_permissions | reviewed_employee_fields
            catalog_codes = set(role_catalog.values_list("code", flat=True))
            missing_codes = catalog_codes - current_codes
            stale_codes = current_codes - catalog_codes
            if missing_codes or stale_codes:
                issues.append(
                    f"administrator_permissions:{role.tenant_id}:"
                    f"missing={','.join(sorted(missing_codes))}:stale={','.join(sorted(stale_codes))}"
                )
                if not readonly:
                    role.permissions.set(role_catalog)

        # Keep the stable built-in role codes while repairing display labels
        # and protection metadata for tenants created before the role catalog
        # was introduced.  Other role codes remain tenant-owned custom roles.
        for code, name in BUILTIN_ROLE_DISPLAY_NAMES.items():
            updates = {
                "name": name,
                "description": BUILTIN_ROLE_DESCRIPTIONS.get(code, ""),
                "role_type": Role.RoleType.BUILTIN,
                "is_protected": True,
            }
            for role in Role.objects.filter(code=code):
                stale_fields = [field for field, value in updates.items() if getattr(role, field) != value]
                if stale_fields:
                    issues.append(f"role_metadata:{role.tenant_id}:{code}:{','.join(stale_fields)}")
                    if not readonly:
                        for field, value in updates.items():
                            setattr(role, field, value)
                        role.save(update_fields=list(updates) + ["updated_at"])

        if options["report_json"]:
            inactive = inactive_permissions()
            self.stdout.write(json.dumps({
                "read_only": readonly,
                "catalog_code_count": len(definitions_by_code),
                "orphan_permission_count": orphan_count,
                "active_orphan_permission_count": active_orphan_count,
                "inactive_permission_count": inactive.count(),
                "inactive_role_link_count": Permission.roles.through.objects.filter(
                    permission_id__in=inactive.values("pk"),
                ).count(),
                "potentially_affected_users": inactive.filter(
                    roles__status=Role.Status.ACTIVE,
                ).values("roles__user_roles__user_id").exclude(
                    roles__user_roles__user_id=None,
                ).distinct().count(),
                "orphan_samples": list(orphan_permissions.order_by("code").values(
                    "code", "permission_type", "metadata",
                )[:20]),
                "issue_count": len(issues),
                "issue_samples": issues[:20],
            }, ensure_ascii=False))

        if readonly and issues:
            mode = "检查" if options["check"] else "预演"
            raise CommandError(
                f"权限登记源存在漂移（{mode}未写入数据库）：" + "; ".join(issues)
            )
        if options["check"]:
            self.stdout.write(self.style.SUCCESS("Permission catalog is complete."))
        elif options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Permission catalog dry-run is clean."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Permission catalog synchronized ({len(definitions_by_code)} codes; "
                    f"created={created}, repaired={repaired}, retired={retired}, touched={touched})."
                )
            )
