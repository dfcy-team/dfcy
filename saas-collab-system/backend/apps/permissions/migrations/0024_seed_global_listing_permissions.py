from django.db import migrations


PERMISSIONS = (
    ("listings.workbench.view", "\u67e5\u770b\u5168\u7403\u520a\u767b\u5de5\u4f5c\u53f0", "listings", "workbench.view"),
    ("listings.workbench.manage", "\u7ba1\u7406\u5168\u7403\u520a\u767b\u5de5\u4f5c\u53f0", "listings", "workbench.manage"),
    ("listings.mapping.view", "\u67e5\u770b\u5e73\u53f0\u7c7b\u76ee\u4e0e\u5c5e\u6027\u6620\u5c04", "listings", "mapping.view"),
    ("listings.mapping.manage", "\u7ef4\u62a4\u5e73\u53f0\u7c7b\u76ee\u4e0e\u5c5e\u6027\u6620\u5c04", "listings", "mapping.manage"),
    ("listings.task.view", "\u67e5\u770b\u5168\u7403\u520a\u767b\u4efb\u52a1\u4e0e\u520a\u767b\u65e5\u5fd7", "listings", "task.view"),
    ("listings.task.manage", "\u7ba1\u7406\u5168\u7403\u520a\u767b\u4efb\u52a1", "listings", "task.manage"),
    ("listings.publish.production", "\u786e\u8ba4\u751f\u4ea7\u520a\u767b", "listings", "publish.production"),
)


def seed_global_listing_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")

    permission_map = {}
    for code, name, module, action in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": "Global listing phase-one tenant-scoped permission.",
            },
        )
        permission_map[code] = permission

    for role in Role.objects.filter(code__in=("administrator", "operations", "product_developer")):
        role.permissions.add(*permission_map.values())
        DataScope.objects.get_or_create(
            tenant=role.tenant,
            role=role,
            scope_type="all" if role.code in {"administrator", "product_developer"} else "own",
            defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0023_create_tenant_administrator_role")]
    operations = [migrations.RunPython(seed_global_listing_permissions, migrations.RunPython.noop)]
