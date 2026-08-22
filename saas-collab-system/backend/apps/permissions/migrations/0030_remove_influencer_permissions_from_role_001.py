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


def remove_influencer_permissions_from_role_001(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")

    influencer_permissions = list(Permission.objects.filter(code__in=INFLUENCER_CODES))
    for role in Role.objects.filter(code="001"):
        role.permissions.remove(*influencer_permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0029_sync_influencer_permission_descriptions")]
    operations = [
        migrations.RunPython(remove_influencer_permissions_from_role_001, migrations.RunPython.noop),
    ]
