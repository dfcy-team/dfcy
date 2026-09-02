from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    definitions = (
        ("influencers.view", "View influencers", "view", "View tenant-scoped influencer profiles and masked contact details."),
        ("influencers.manage", "Manage influencers", "manage", "Create, update, activate, and deactivate tenant-scoped influencer profiles."),
    )
    permissions = []
    for code, name, action, description in definitions:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "influencers", "action": action, "description": description},
        )
        permissions.append(permission)
    for role in Role.objects.filter(code="001", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0020_seed_product_development_listing_roles")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
