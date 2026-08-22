from django.db import migrations


INFLUENCER_CODES = (
    "influencers.view",
    "influencers.manage",
    "influencers.outreach.view",
    "influencers.outreach.manage",
    "influencers.fulfillment.view",
    "influencers.fulfillment.manage",
    "influencers.catalog.view",
)


def apply_forward_fixes(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")

    influencer_permissions = list(Permission.objects.filter(code__in=INFLUENCER_CODES))
    for role in Role.objects.filter(code="001", status="active"):
        role.permissions.add(*influencer_permissions)

    for role in Role.objects.filter(code="002", status="active"):
        role.name = "达人管理"
        role.save(update_fields=["name"])
        role.permissions.add(*influencer_permissions)

    for role in Role.objects.filter(code="administrator", status="active"):
        role.name = "管理员"
        role.save(update_fields=["name"])
        role.permissions.add(*influencer_permissions)

    research_permissions = list(
        Permission.objects.filter(code__in=("products.research.view", "products.research.manage"))
    )
    for role in Role.objects.filter(code="operations", status="active"):
        role.permissions.add(*research_permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0027_merge_influencer_and_shipment_permissions")]
    operations = [migrations.RunPython(apply_forward_fixes, migrations.RunPython.noop)]
