from django.db import migrations


PERMISSION_CODE = "supply.purchase_order.assign_shipping_route"


def seed_permission(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    permission.objects.update_or_create(
        code=PERMISSION_CODE,
        defaults={
            "name": "Assign purchase-order shipping route",
            "module": "supply",
            "action": "purchase_order.assign_shipping_route",
            "description": (
                "Assign or correct the loose-cargo/container-cargo route after production "
                "completion within the authorized data scope."
            ),
        },
    )


def remove_permission(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    permission.objects.filter(code=PERMISSION_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("permissions", "0018_seed_packing_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_permission, remove_permission),
    ]
