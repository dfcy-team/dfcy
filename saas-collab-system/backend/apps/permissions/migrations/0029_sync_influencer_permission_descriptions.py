from django.db import migrations


DESCRIPTIONS = {
    "influencers.view": "View tenant-scoped influencer profiles and masked contact details.",
    "influencers.manage": "Create, update, activate, and deactivate tenant-scoped influencer profiles.",
}


def sync_descriptions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, description in DESCRIPTIONS.items():
        Permission.objects.filter(code=code).update(description=description)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0028_forward_fix_creator_role_permissions")]
    operations = [migrations.RunPython(sync_descriptions, migrations.RunPython.noop)]
