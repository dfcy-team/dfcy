from django.db import migrations


PERMISSIONS = (
    ("development.requirement.view", "View product requirements", "development", "requirement.view"),
    ("development.requirement.manage", "Manage own product requirements", "development", "requirement.manage"),
    ("development.requirement.review", "Review product requirements", "development", "requirement.review"),
    ("development.project.view", "View development projects", "development", "project.view"),
    ("development.project.manage", "Manage development projects", "development", "project.manage"),
    ("development.project.approve", "Approve development stages", "development", "project.approve"),
    ("development.sample.view", "View development samples", "development", "sample.view"),
    ("development.sample.manage", "Manage development samples", "development", "sample.manage"),
    ("development.cost.view", "View development costs", "development", "cost.view"),
    ("development.cost.manage", "Manage development costs", "development", "cost.manage"),
    ("development.cost.approve", "Approve development costs", "development", "cost.approve"),
    ("development.sales.view", "View product sales snapshots", "development", "sales.view"),
    ("development.sales.import", "Import product sales snapshots", "development", "sales.import"),
    ("development.review.view", "View product performance reviews", "development", "review.view"),
    ("development.review.manage", "Manage product performance reviews", "development", "review.manage"),
    ("development.review.approve", "Approve product performance reviews", "development", "review.approve"),
    ("development.dashboard.view", "View development performance dashboard", "development", "dashboard.view"),
    ("listings.template.view", "View listing templates", "listings", "template.view"),
    ("listings.template.manage", "Manage listing templates", "listings", "template.manage"),
    ("listings.profile.view", "View listing profiles", "listings", "profile.view"),
    ("listings.profile.manage", "Manage listing drafts", "listings", "profile.manage"),
    ("listings.profile.approve", "Approve listing profiles", "listings", "profile.approve"),
    ("listings.profile.publish", "Publish approved listings", "listings", "profile.publish"),
)


ROLE_DEFINITIONS = {
    "operations": {
        "name": "Operations",
        "scope": "own",
        "permissions": (
            "development.requirement.view",
            "development.requirement.manage",
            "development.project.view",
            "development.sales.view",
            "listings.template.view",
            "listings.profile.view",
            "listings.profile.manage",
        ),
    },
    "product_developer": {
        "name": "Product Developer",
        "scope": "all",
        "permissions": (
            "development.project.view",
            "development.project.manage",
            "development.sample.view",
            "development.sample.manage",
            "development.cost.view",
            "development.cost.manage",
            "development.sales.view",
            "development.sales.import",
            "development.review.view",
            "development.review.manage",
            "development.dashboard.view",
            "listings.template.view",
            "listings.template.manage",
            "listings.profile.view",
            "listings.profile.manage",
            "products.master.view",
            "masterdata.view",
        ),
    },
}


def seed_roles_and_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    Tenant = apps.get_model("tenants", "Tenant")

    permission_map = {}
    for code, name, module, action in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": "Product development and controlled multi-platform listing permission.",
            },
        )
        permission_map[code] = permission

    for code in {"products.master.view", "masterdata.view"}:
        permission = Permission.objects.filter(code=code).first()
        if permission:
            permission_map[code] = permission

    for tenant in Tenant.objects.all().iterator():
        for role_code, definition in ROLE_DEFINITIONS.items():
            role, _ = Role.objects.update_or_create(
                tenant=tenant,
                code=role_code,
                defaults={"name": definition["name"], "status": "active"},
            )
            role.permissions.set(
                permission_map[code]
                for code in definition["permissions"]
                if code in permission_map
            )
            DataScope.objects.update_or_create(
                tenant=tenant,
                role=role,
                scope_type=definition["scope"],
                defaults={"config": {}},
            )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0019_seed_shipping_route_permission")]
    operations = [
        migrations.RunPython(seed_roles_and_permissions, migrations.RunPython.noop),
    ]
