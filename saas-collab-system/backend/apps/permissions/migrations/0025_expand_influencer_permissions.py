from django.db import migrations


PERMISSIONS = (
    ("influencers.outreach.view", "View outreach tasks", "outreach.view", "View tenant-scoped influencer outreach tasks."),
    ("influencers.outreach.manage", "Manage outreach tasks", "outreach.manage", "Create and transition audited tenant-scoped outreach tasks."),
    ("influencers.fulfillment.view", "View sample fulfillment", "fulfillment.view", "View tenant-scoped sample fulfillment records."),
    ("influencers.fulfillment.manage", "Manage sample fulfillment", "fulfillment.manage", "Create idempotent sample requests and transition fulfillment status."),
    ("influencers.catalog.view", "View influencer product prices", "catalog.view", "Query tenant, store and site scoped SKU price snapshots."),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action, description in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "influencers",
                "action": action,
                "description": description,
            },
        )
        permissions.append(permission)
    for role in Role.objects.filter(code__in=("002", "administrator"), status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0024_seed_global_listing_permissions")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
