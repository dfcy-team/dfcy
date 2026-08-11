from django.core.management.base import BaseCommand, CommandError

from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission, Role
from apps.permissions.role_catalog import TENANT_ADMIN_ROLE_CODE


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
        for definition in PERMISSION_DEFINITIONS:
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

        if options["check"] and issues:
            raise CommandError("Permission catalog is incomplete or stale: " + "; ".join(issues))

        if options["check"]:
            self.stdout.write(self.style.SUCCESS("Permission catalog is complete."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Permission catalog synchronized ({len(PERMISSION_DEFINITIONS)} codes)."))
