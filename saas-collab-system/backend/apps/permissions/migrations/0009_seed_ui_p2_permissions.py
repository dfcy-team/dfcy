from django.db import migrations


PERMISSIONS = (
    ("system.organization.view", "View organization directory", "system", "organization.view", "View tenant-scoped departments and organization structure."),
    ("system.organization.manage", "Manage organization directory", "system", "organization.manage", "Create and update tenant-scoped departments."),
    ("system.users.view", "View user directory", "system", "users.view", "View masked tenant-scoped user account metadata."),
    ("system.users.manage", "Manage user directory", "system", "users.manage", "Create, activate, deactivate, and assign roles to tenant users."),
    ("system.roles.view", "View roles and permissions", "system", "roles.view", "View tenant roles, permission catalog, and data scopes."),
    ("system.roles.manage", "Manage roles and permissions", "system", "roles.manage", "Create roles and update tenant role permissions and data scopes."),
    ("masterdata.view", "View master data", "masterdata", "view", "View tenant-scoped platform, store, warehouse, and supplier archives."),
    ("masterdata.manage", "Manage master data", "masterdata", "manage", "Create, update, activate, and deactivate tenant master data."),
    ("security.operations.view", "View security operations", "security", "operations.view", "View masked credential metadata and tenant operation audit summaries."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0008_seed_report_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
