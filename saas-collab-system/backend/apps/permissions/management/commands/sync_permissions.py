from django.core.management.base import BaseCommand, CommandError

from apps.permissions.catalog import ALL_PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission, Role
from apps.permissions.role_catalog import (
    BUILTIN_ROLE_DESCRIPTIONS,
    BUILTIN_ROLE_DISPLAY_NAMES,
    TENANT_ADMIN_ROLE_CODE,
)


class Command(BaseCommand):
    help = "Create or validate the application permission catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Fail if any permission is missing or has stale metadata.",
        )

    def handle(self, *args, **options):
        issues = []
        for definition in ALL_PERMISSION_DEFINITIONS:
            code = definition["code"]
            defaults = permission_defaults(definition)
            permission = Permission.objects.filter(code=code).first()
            if permission is None:
                issues.append(f"missing:{code}")
                if not options["check"]:
                    Permission.objects.create(code=code, **defaults)
                continue

            stale_fields = [field for field, value in defaults.items() if getattr(permission, field) != value]
            if stale_fields:
                issues.append(f"stale:{code}:{','.join(stale_fields)}")
                if not options["check"]:
                    for field, value in defaults.items():
                        setattr(permission, field, value)
                    permission.save(update_fields=list(defaults))

        # The tenant administrator is a catalog-managed role.  New permission
        # definitions must be granted to it automatically; otherwise a newly
        # added capability can make the UI appear incomplete until a manual
        # role edit (which is intentionally blocked for this built-in role).
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
                if not options["check"]:
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
                    if not options["check"]:
                        for field, value in updates.items():
                            setattr(role, field, value)
                        role.save(update_fields=list(updates) + ["updated_at"])

        if options["check"] and issues:
            raise CommandError("Permission catalog is incomplete or stale: " + "; ".join(issues))

        if options["check"]:
            self.stdout.write(self.style.SUCCESS("Permission catalog is complete."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Permission catalog synchronized ({len(ALL_PERMISSION_DEFINITIONS)} codes)."))
