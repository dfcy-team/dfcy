from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action in (("influencers.view", "View influencers", "view"), ("influencers.manage", "Manage influencers", "manage")):
        Permission.objects.update_or_create(code=code, defaults={"name": name, "module": "influencers", "action": action,
            "description": "Tenant-scoped influencer management permission."})


class Migration(migrations.Migration):
    dependencies = [("permissions", "0020_seed_product_development_listing_roles")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
