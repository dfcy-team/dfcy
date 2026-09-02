from django.db import migrations


PERMISSION_DEFINITIONS = (
    (
        "audit.operation_logs.view",
        "View operation audit logs",
        "operation_logs.view",
        "View redacted operation logs within the tenant and assigned data scope.",
    ),
    (
        "audit.operation_logs.export",
        "Export operation audit logs",
        "operation_logs.export",
        "Export redacted operation-log metadata within the tenant and assigned data scope.",
    ),
)


def seed_operation_audit_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action, description in PERMISSION_DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "audit",
                "action": action,
                "description": description,
            },
        )
        permissions.append(permission)

    # The built-in tenant administrator is catalog-managed. Other roles must
    # opt into audit viewing/export explicitly through role administration.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0035_merge_archive_and_platform_permission_metadata")]

    operations = [migrations.RunPython(seed_operation_audit_permissions, migrations.RunPython.noop)]
