from django.db import migrations


PERMISSIONS = (
    ("supply.consolidation_site.view", "View consolidation sites", "consolidation_site.view"),
    ("supply.consolidation_site.manage", "Manage consolidation sites", "consolidation_site.manage"),
    ("supply.consolidation.view", "View consolidations", "consolidation.view"),
    ("supply.consolidation.create", "Create consolidations", "consolidation.create"),
    ("supply.consolidation.manage", "Manage consolidation drafts", "consolidation.manage"),
    ("supply.consolidation.allocate", "Allocate consolidation boxes", "consolidation.allocate"),
    ("supply.consolidation.release", "Release consolidations", "consolidation.release"),
    ("supply.consolidation.receive", "Receive consolidation boxes", "consolidation.receive"),
    ("supply.consolidation.exception.manage", "Manage consolidation exceptions", "consolidation.exception.manage"),
    ("supply.consolidation.transfer", "Transfer consolidation boxes", "consolidation.transfer"),
    ("supply.consolidation.cancel", "Cancel consolidations", "consolidation.cancel"),
)


def seed_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    for code, name, action in PERMISSIONS:
        permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "supply",
                "action": action,
                "description": "SC-CONSOLIDATION-1 frozen local-domain permission.",
            },
        )


def remove_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    permission.objects.filter(code__in=[code for code, _, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("permissions", "0024_seed_global_listing_permissions")]
    operations = [migrations.RunPython(seed_permissions, remove_permissions)]
