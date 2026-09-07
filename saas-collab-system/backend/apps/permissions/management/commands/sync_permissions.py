from django.core.management.base import BaseCommand, CommandError

from apps.permissions.catalog import permission_defaults, runtime_permission_definitions
from apps.permissions.menu_registry import MenuRegistryError
from apps.permissions.models import Permission, Role
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
            if _menu_status(metadata) != "inactive" or metadata.get("registry_source") != MENU_REGISTRY_SOURCE:
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
        for role in Role.objects.prefetch_related("permissions"):
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
                if permission.code not in current_codes and required_actions & action_codes:
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
        all_permissions = Permission.objects.all()
        for role in Role.objects.filter(code=TENANT_ADMIN_ROLE_CODE):
            current_codes = set(role.permissions.values_list("code", flat=True))
            catalog_codes = set(all_permissions.values_list("code", flat=True))
            missing_codes = catalog_codes - current_codes
            stale_codes = current_codes - catalog_codes
            if missing_codes or stale_codes:
                issues.append(
                    f"administrator_permissions:{role.tenant_id}:"
                    f"missing={','.join(sorted(missing_codes))}:stale={','.join(sorted(stale_codes))}"
                )
                if not readonly:
                    role.permissions.set(all_permissions)

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
